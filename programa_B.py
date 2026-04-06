import socket
import threading
import time
import random
import json
import os
from datetime import datetime
 
# CONFIGURAÇÃO
HOST_LOCAL = "127.0.0.1"
PORTA_RECEBER_PEDIDO = 6000
 
MIRTH_HOST = "127.0.0.1"
MIRTH_PORTA_RELATORIO = 5101
 
MLLP_START = b"\x0b"
MLLP_END = b"\x1c\x0d"
 
DB_PATH = "db.json"
 
# Fila de Pedidos Pendentes em memória
fila_pedidos = {}
fila_lock = threading.Lock()
 
# ===============================
# BASE DE DADOS JSON
# ===============================
 
def carregar_db():
    """Carrega a base de dados do ficheiro JSON. Cria estrutura vazia se não existir."""
    if not os.path.exists(DB_PATH):
        return {"pacientes": {}, "pedidos": {}}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        print(f"  [AVISO] Erro ao ler {DB_PATH}. A iniciar base de dados vazia.")
        return {"pacientes": {}, "pedidos": {}}
 
def guardar_db(db):
    """Guarda a base de dados no ficheiro JSON."""
    try:
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"  [ERRO] Não foi possível guardar a base de dados: {e}")
 
def atualizar_estado_pedido_db(order_id, estado, relatorio=None):
    """Atualiza o estado de um pedido na base de dados JSON."""
    db = carregar_db()
    if order_id in db.get("pedidos", {}):
        db["pedidos"][order_id]["estado"] = estado
        if estado == "REALIZADO":
            db["pedidos"][order_id]["realizado_em"] = datetime.now().isoformat()
        if relatorio:
            db["pedidos"][order_id]["relatorio"] = relatorio
        guardar_db(db)
 
def registar_pedido_db_se_novo(order_id, info):
    """Regista um pedido na DB se ainda não existir (para pedidos que chegam só pelo Mirth)."""
    db = carregar_db()
    if order_id not in db.get("pedidos", {}):
        db["pedidos"][order_id] = {
            "order_id": order_id,
            "pid": info.get("pid", ""),
            "nome_paciente": info.get("nome", ""),
            "tipo": "Desconhecido",
            "exame": {
                "codigo": info.get("codigo_exame", ""),
                "descricao": info.get("desc_exame", "")
            },
            "estado": "PENDENTE",
            "enviado_em": datetime.now().isoformat(),
            "realizado_em": None,
            "relatorio": None
        }
        guardar_db(db)
 
def listar_pacientes_db():
    db = carregar_db()
    return db.get("pacientes", {})
 
def pedidos_por_paciente_db(pid):
    db = carregar_db()
    return {oid: p for oid, p in db.get("pedidos", {}).items() if p.get("pid") == pid}
 
# ===============================
# MLLP
# ===============================
 
def envolver_mllp(mensagem):
    return MLLP_START + mensagem.encode("utf-8") + MLLP_END
 
def remover_mllp(dados):
    if dados.startswith(MLLP_START):
        dados = dados[1:]
    if dados.endswith(MLLP_END):
        dados = dados[:-2]
    return dados.decode("utf-8", errors="replace")
 
# ===============================
# PARSING HL7
# ===============================
 
def extrair_campo(segmento, indice):
    partes = segmento.split("|")
    return partes[indice] if len(partes) > indice else ""
 
def parse_mensagem_hl7(mensagem):
    info = {
        "tipo_msg": "",
        "pid": "",
        "nome": "",
        "sexo": "",
        "dob": "",
        "order_id": "",
        "codigo_exame": "",
        "desc_exame": "",
        "acao_orc": "",
        "tipo_visita": "",
    }
 
    segmentos = mensagem.strip().split("\r")
    for seg in segmentos:
        campos = seg.split("|")
        tipo = campos[0] if campos else ""
 
        if tipo == "MSH":
            info["tipo_msg"] = extrair_campo(seg, 8)
        elif tipo == "PID":
            info["pid"]  = extrair_campo(seg, 3)
            info["nome"] = extrair_campo(seg, 5)
            info["dob"]  = extrair_campo(seg, 7)
            info["sexo"] = extrair_campo(seg, 8)
        elif tipo == "PV1":
            info["tipo_visita"] = extrair_campo(seg, 2)
        elif tipo == "ORC":
            info["acao_orc"] = extrair_campo(seg, 1)
            info["order_id"] = extrair_campo(seg, 2)
        elif tipo == "OBR":
            info["order_id"]     = extrair_campo(seg, 2) or info["order_id"]
            exame_full           = extrair_campo(seg, 4)
            partes_exame         = exame_full.split("^")
            info["codigo_exame"] = partes_exame[0]
            info["desc_exame"]   = partes_exame[1] if len(partes_exame) > 1 else exame_full
 
    return info
 
# ===============================
# GERAÇÃO DE RELATÓRIOS HL7
# ===============================
 
def gerar_resultado_simulado(codigo_exame, desc_exame, tipo_msg):
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
 
    if "OML" in tipo_msg or any(c in codigo_exame for c in ["258", "609", "HEM"]):
        resultados_lab = {
            "25826": ("Ureia",                 "42",      "mg/dL",  "10-50"),
            "25813": ("Potassio",              "4.1",     "mmol/L", "3.5-5.0"),
            "HEM01": ("Hemoglobina",           "13.5",    "g/dL",   "12.0-16.0"),
            "60996": ("Estudo bacteriologico", "Negativo","",       "Negativo"),
        }
        resultado = resultados_lab.get(
            codigo_exame,
            (desc_exame, str(round(random.uniform(3, 10), 1)), "U", "N/A")
        )
        nome_r, valor, unidade, ref = resultado
        obx = f"OBX|1|NM|{codigo_exame}^{nome_r}||{valor}|{unidade}|{ref}|N|||F|||{agora}\r"
        return obx, "Resultado laboratorial dentro dos valores de referência."
 
    elif any(c in codigo_exame for c in ["M10", "TAC", "ECO"]):
        descricoes = [
            "Sem alterações significativas. Estruturas anatómicas preservadas.",
            "Exame realizado com sucesso. Sem lesões agudas identificadas.",
            "Imagem compatível com variante da normalidade. Sem sinais de patologia aguda.",
        ]
        texto = random.choice(descricoes)
        obx = (
            f"OBX|1|TX|RESULTADO||{texto}||||||F|||{agora}\r"
            f"OBX|2|TX|CONCLUSAO||Exame validado pelo especialista.||||||F|||{agora}\r"
        )
        return obx, texto
 
    else:
        obx = f"OBX|1|TX|RESULTADO||Exame realizado com sucesso. Valores dentro da normalidade.||||||F|||{agora}\r"
        return obx, "Exame realizado com sucesso."
 
def criar_relatorio_hl7(info):
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
    order_id = info["order_id"] or "EX000"
    obx_linhas, _ = gerar_resultado_simulado(
        info["codigo_exame"], info["desc_exame"], info["tipo_msg"]
    )
    msg  = f"MSH|^~\\&|ProgramaB|Laboratorio|Mirth|Clinica|{agora}||ORU^R01|RPT{agora}|P|2.5\r"
    msg += f"PID|1||{info['pid']}||{info['nome']}||{info['dob']}|{info['sexo']}\r"
    msg += f"ORC|RE|{order_id}|{order_id}||CM||||{agora}\r"
    msg += f"OBR|1|{order_id}|{order_id}|{info['codigo_exame']}^{info['desc_exame']}|{agora}|||||||||||||||||||||||||||F\r"
    msg += obx_linhas
    return msg
 
def criar_ack_admissao(info):
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
    msg  = f"MSH|^~\\&|ProgramaB|Hospital|Mirth|Clinica|{agora}||ADT^A01|ACK{agora}|P|2.5\r"
    msg += f"MSA|AA|{agora}|Admissao registada com sucesso.\r"
    msg += f"PID|1||{info['pid']}||{info['nome']}||{info['dob']}|{info['sexo']}\r"
    return msg
 
# ===============================
# ENVIO PARA MIRTH
# ===============================
 
def enviar_para_mirth(mensagem):
    pacote = envolver_mllp(mensagem)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as cliente:
            cliente.connect((MIRTH_HOST, MIRTH_PORTA_RELATORIO))
            cliente.sendall(pacote)
        return True
    except ConnectionRefusedError:
        print("  [ERRO] Não foi possível ligar ao Mirth. Canal ativo?")
        return False
 
# ===============================
# ESTATÍSTICAS
# ===============================
 
stats = {"recebidos": 0, "enviados": 0, "cancelamentos": 0, "admissoes": 0, "erros": 0}
 
# ===============================
# PROCESSAMENTO DE MENSAGENS
# ===============================
 
def processar_mensagem(dados_raw, addr):
    dados = remover_mllp(dados_raw)
 
    print("\n" + "─"*52)
    print(f"  [RECEBIDO] de {addr}")
    print("─"*52)
    print(dados)
    print("─"*52)
 
    info = parse_mensagem_hl7(dados)
    tipo_msg = info["tipo_msg"]
    acao     = info["acao_orc"]
    order_id = info["order_id"]
 
    # --- Cancelamento ---
    if acao == "CA":
        with fila_lock:
            entrada = fila_pedidos.get(order_id)
            if not entrada:
                print(f"\n  [AVISO] Cancelamento para order_id desconhecido: {order_id}\n")
                stats["erros"] += 1
                return
            if entrada["estado"] == "REALIZADO":
                print(f"\n  [REJEITADO] Exame {order_id} já foi realizado. Cancelamento impossível.\n")
                stats["erros"] += 1
                return
            if entrada["estado"] == "CANCELADO":
                print(f"\n  [AVISO] Pedido {order_id} já estava cancelado.\n")
                return
            entrada["estado"] = "CANCELADO"
 
        # Atualizar na base de dados
        atualizar_estado_pedido_db(order_id, "CANCELADO")
        stats["cancelamentos"] += 1
        print(f"\n  [CANCELAMENTO] Pedido {order_id} cancelado. Nenhum relatório será gerado.\n")
 
    # --- Admissão ---
    elif "ADT" in tipo_msg:
        stats["recebidos"] += 1
        stats["admissoes"] += 1
        resposta = criar_ack_admissao(info)
        print(f"\n  [ADMISSÃO] {info['nome']} (PID: {info['pid']})")
        if enviar_para_mirth(resposta):
            print("  [OK] Confirmação de admissão enviada.\n")
        else:
            stats["erros"] += 1
 
    # --- Pedido novo de exame ou análise ---
    elif acao in ("NW", "") and tipo_msg in ("ORM^O01", "OML^O21", ""):
        stats["recebidos"] += 1
        with fila_lock:
            fila_pedidos[order_id] = {
                "info": info,
                "estado": "PENDENTE",
                "recebido_em": datetime.now(),
            }
 
        # Garantir que o pedido está registado na base de dados
        registar_pedido_db_se_novo(order_id, info)
 
        print(f"\n  [FILA] Pedido {order_id} adicionado como PENDENTE.")
        print(f"  Doente : {info['nome']}  |  Exame: {info['desc_exame']}")
        print("  Use a opção [3] do menu para realizar exames pendentes.\n")
 
    else:
        print(f"  [AVISO] Mensagem não reconhecida: tipo={tipo_msg}, acao={acao}")
        stats["erros"] += 1
 
def tratar_conexao(conn, addr):
    with conn:
        buffer = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk
            if MLLP_END in buffer:
                break
        processar_mensagem(buffer, addr)
 
# ===============================
# SERVIDOR
# ===============================
 
servidor_ativo = False
servidor_socket = None
 
def iniciar_servidor():
    global servidor_ativo, servidor_socket
    servidor_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor_socket.bind((HOST_LOCAL, PORTA_RECEBER_PEDIDO))
    servidor_socket.listen(5)
    servidor_ativo = True
    print(f"\n  [SERVIDOR] À escuta na porta {PORTA_RECEBER_PEDIDO}...")
    while servidor_ativo:
        try:
            conn, addr = servidor_socket.accept()
            t = threading.Thread(target=tratar_conexao, args=(conn, addr), daemon=True)
            t.start()
        except OSError:
            break
 
# ===============================
# AÇÕES DO MENU
# ===============================
 
def mostrar_fila():
    print("\n  FILA DE PEDIDOS")
    print("  ─────────────────────────────────────────")
    with fila_lock:
        pendentes  = {k: v for k, v in fila_pedidos.items() if v["estado"] == "PENDENTE"}
        realizados = {k: v for k, v in fila_pedidos.items() if v["estado"] == "REALIZADO"}
        cancelados = {k: v for k, v in fila_pedidos.items() if v["estado"] == "CANCELADO"}
 
        if not fila_pedidos:
            print("  (fila vazia)")
        else:
            if pendentes:
                print("  [PENDENTES] — aguardam realização pelo operador:")
                for oid, e in pendentes.items():
                    t = e["recebido_em"].strftime("%H:%M:%S")
                    print(f"    [{oid}]  {e['info']['nome']}  —  {e['info']['desc_exame']}  —  recebido às {t}")
            if realizados:
                print("  [REALIZADOS]:")
                for oid, e in realizados.items():
                    print(f"    [{oid}]  {e['info']['nome']}  —  {e['info']['desc_exame']}")
            if cancelados:
                print("  [CANCELADOS]:")
                for oid, e in cancelados.items():
                    print(f"    [{oid}]  {e['info']['nome']}  —  {e['info']['desc_exame']}")
 
def realizar_exames_pendentes():
    """Operador escolhe quais pedidos pendentes realizar e gerar relatório."""
    with fila_lock:
        pendentes = {k: v for k, v in fila_pedidos.items() if v["estado"] == "PENDENTE"}
 
    if not pendentes:
        print("\n  [INFO] Não há pedidos pendentes para realizar.")
        return
 
    print("\n  PEDIDOS PENDENTES")
    for oid, e in pendentes.items():
        t = e["recebido_em"].strftime("%H:%M:%S")
        print(f"  [{oid}]  {e['info']['nome']}  —  {e['info']['desc_exame']}  —  recebido às {t}")
    print("  Introduza o Order ID a realizar (ou 'TODOS' para realizar todos):")
    escolha = input("  Opção: ").strip().strip("[]").upper()
 
    if escolha == "TODOS":
        ordens_a_realizar = list(pendentes.keys())
    elif escolha in pendentes:
        ordens_a_realizar = [escolha]
    else:
        print("  [ERRO] Order ID não encontrado na lista de pendentes.")
        return
 
    for oid in ordens_a_realizar:
        with fila_lock:
            entrada = fila_pedidos.get(oid)
            if not entrada or entrada["estado"] != "PENDENTE":
                print(f"  [AVISO] {oid} já não está pendente, a saltar.")
                continue
            entrada["estado"] = "REALIZADO"
            info = entrada["info"]
 
        relatorio = criar_relatorio_hl7(info)
        print(f"\n  [REALIZANDO] {oid}  —  {info['nome']}  —  {info['desc_exame']}")
        print("  Relatório HL7 a enviar:")
        for linha in relatorio.strip().split("\r"):
            print(f"  │ {linha}")
 
        if enviar_para_mirth(relatorio):
            print(f"  [OK] Relatório enviado ao Mirth.\n")
            stats["enviados"] += 1
            # Guardar relatório na base de dados JSON
            atualizar_estado_pedido_db(oid, "REALIZADO", relatorio=relatorio)
        else:
            with fila_lock:
                fila_pedidos[oid]["estado"] = "PENDENTE"
            print(f"  [ERRO] Falha no envio. Pedido {oid} revertido para PENDENTE.\n")
            stats["erros"] += 1
 
def ver_pedidos_por_paciente():
    """Mostra todos os pedidos e relatórios de um paciente específico."""
    pacientes = listar_pacientes_db()
 
    print("\n  CONSULTA DE PEDIDOS POR PACIENTE")
    print("  ─────────────────────────────────────────")
    if not pacientes:
        print("  (nenhum paciente registado na base de dados)")
        return
 
    for pid, p in pacientes.items():
        print(f"  [{pid}]  {p['nome']}  |  DN: {p['dob']}  |  Sexo: {p['sexo']}")
 
    pid = input("\n  Introduza o PID do paciente: ").strip()
    if pid not in pacientes:
        print(f"  [ERRO] Paciente com PID '{pid}' não encontrado.")
        return
 
    paciente = pacientes[pid]
    pedidos  = pedidos_por_paciente_db(pid)
 
    print(f"\n  PEDIDOS DE {paciente['nome'].upper()} (PID: {pid})")
    print("  ─────────────────────────────────────────")
 
    if not pedidos:
        print("  (nenhum pedido registado para este paciente)")
        return
 
    for oid, p in pedidos.items():
        estado = p.get("estado", "?")
        tipo   = p.get("tipo", "?")
        exame  = p.get("exame", {})
        desc   = exame.get("descricao", "?") if isinstance(exame, dict) else str(exame)
        env    = p.get("enviado_em", "")[:16].replace("T", " ")
        real   = p.get("realizado_em", "")
        real_str = real[:16].replace("T", " ") if real else "—"
 
        print(f"\n  [{oid}]  {tipo}  —  {desc}")
        print(f"    Estado     : {estado}")
        print(f"    Enviado em : {env}")
        print(f"    Realizado  : {real_str}")
 
        if estado == "REALIZADO" and p.get("relatorio"):
            ver_rel = input("    Ver relatório completo? (S/N): ").strip().upper()
            if ver_rel == "S":
                print("  ┌─ RELATÓRIO HL7 " + "─"*35)
                for linha in p["relatorio"].strip().split("\r"):
                    print(f"  │ {linha}")
                print("  └" + "─"*51)
 
def mostrar_stats():
    print("\n  ESTATÍSTICAS DE OPERAÇÃO")
    with fila_lock:
        pendentes  = sum(1 for v in fila_pedidos.values() if v["estado"] == "PENDENTE")
        realizados = sum(1 for v in fila_pedidos.values() if v["estado"] == "REALIZADO")
        cancelados = sum(1 for v in fila_pedidos.values() if v["estado"] == "CANCELADO")
 
    # Totais da base de dados (inclui sessões anteriores)
    db = carregar_db()
    total_pedidos_db = len(db.get("pedidos", {}))
    total_pacientes  = len(db.get("pacientes", {}))
 
    print(f"  ── Sessão atual ──────────────────────────")
    print(f"  Pedidos recebidos  : {stats['recebidos']}")
    print(f"  — Em espera        : {pendentes}")
    print(f"  — Realizados       : {realizados}")
    print(f"  — Cancelados       : {cancelados}")
    print(f"  Relatórios enviados: {stats['enviados']}")
    print(f"  Admissões          : {stats['admissoes']}")
    print(f"  Erros / Rejeitados : {stats['erros']}")
    print(f"  ── Base de dados ─────────────────────────")
    print(f"  Pacientes registados : {total_pacientes}")
    print(f"  Pedidos totais (DB)  : {total_pedidos_db}")
 
# ===============================
# MENU
# ===============================
 
def cabecalho():
    print("    SISTEMA DE REALIZAÇÃO DE EXAMES — LABORATÓRIO     ")
    print("              Programa B  —  Servidor HL7              ")
    print("")
 
def menu_b():
    with fila_lock:
        n_pendentes = sum(1 for v in fila_pedidos.values() if v["estado"] == "PENDENTE")
    if n_pendentes > 0:
        print(f"\n  !! {n_pendentes} pedido(s) pendente(s) a aguardar realização!")
    print("\n  MENU")
    print("  [1] Ver estatísticas")
    print("  [2] Ver fila de pedidos")
    print("  [3] Realizar exames pendentes")
    print("  [4] Ver pedidos por paciente")
    print("  [0] Parar servidor e sair")
    return input("  Opção: ").strip()
 
# ===============================
# MAIN
# ===============================
 
if __name__ == "__main__":
    print("\033[2J\033[H", end="")
    cabecalho()
 
    t_servidor = threading.Thread(target=iniciar_servidor, daemon=True)
    t_servidor.start()
    time.sleep(0.5)
 
    # Resumo da base de dados ao arrancar
    db_inicial = carregar_db()
    n_pac  = len(db_inicial.get("pacientes", {}))
    n_ped  = len(db_inicial.get("pedidos", {}))
    print(f"\n  Base de dados: {n_pac} paciente(s), {n_ped} pedido(s) registado(s).")
    print("\n  Servidor iniciado. À espera de pedidos do Mirth...\n")
    print("  Pedidos recebidos ficam PENDENTES até o operador os realizar (opção [3]).\n")
 
    while True:
        opcao = menu_b()
        if opcao == "1":
            mostrar_stats()
        elif opcao == "2":
            mostrar_fila()
        elif opcao == "3":
            realizar_exames_pendentes()
        elif opcao == "4":
            ver_pedidos_por_paciente()
        elif opcao == "0":
            print("\n  A parar o servidor... Até logo!\n")
            servidor_ativo = False
            if servidor_socket:
                servidor_socket.close()
            break
        else:
            print("  Opção inválida.")
        input("\n  Prima Enter para continuar...")
        print("\033[2J\033[H", end="")
        cabecalho()
        print(f"\n  [SERVIDOR ATIVO — porta {PORTA_RECEBER_PEDIDO}]\n")