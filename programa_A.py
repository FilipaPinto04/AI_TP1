import socket
import threading
import time
import json
import os
import re
from datetime import datetime
 
# CONFIGURAÇÃO
MIRTH_HOST = "127.0.0.1"
MIRTH_PORTA_PEDIDO = 5100
 
HOST_LOCAL = "127.0.0.1"
PORTA_RELATORIO = 6001
 
MLLP_START = b"\x0b"
MLLP_END = b"\x1c\x0d"
 
DB_PATH = "db.json"
 
_msg_counter = 0
 
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
 
def registar_paciente_db(paciente):
    """Regista ou atualiza um paciente na base de dados."""
    db = carregar_db()
    pid = paciente["pid"]
    db["pacientes"][pid] = {
        **paciente,
        "registado_em": datetime.now().isoformat()
    }
    guardar_db(db)
 
def obter_paciente_db(pid):
    """Devolve os dados de um paciente pelo PID, ou None se não existir."""
    db = carregar_db()
    return db["pacientes"].get(pid)
 
def listar_pacientes_db():
    """Devolve todos os pacientes registados."""
    db = carregar_db()
    return db["pacientes"]
 
def registar_pedido_db(order_id, paciente, tipo, exame_ou_analise, estado="PENDENTE"):
    """Regista um novo pedido na base de dados."""
    db = carregar_db()
    db["pedidos"][order_id] = {
        "order_id": order_id,
        "pid": paciente["pid"],
        "nome_paciente": paciente["nome"],
        "tipo": tipo,
        "exame": exame_ou_analise,
        "estado": estado,
        "enviado_em": datetime.now().isoformat(),
        "realizado_em": None,
        "relatorio": None
    }
    guardar_db(db)
 
def atualizar_estado_pedido_db(order_id, estado, relatorio=None):
    """Atualiza o estado de um pedido na base de dados."""
    db = carregar_db()
    if order_id in db["pedidos"]:
        db["pedidos"][order_id]["estado"] = estado
        if estado == "REALIZADO":
            db["pedidos"][order_id]["realizado_em"] = datetime.now().isoformat()
        if relatorio:
            db["pedidos"][order_id]["relatorio"] = relatorio
        guardar_db(db)
 
def pedidos_por_paciente_db(pid):
    """Devolve todos os pedidos de um paciente."""
    db = carregar_db()
    return {oid: p for oid, p in db["pedidos"].items() if p["pid"] == pid}
 
# ===============================
# CONTADORES E MLLP
# ===============================
 
def gerar_msg_id():
    global _msg_counter
    _msg_counter += 1
    return f"MSG{_msg_counter:04d}"
 
def gerar_order_id():
    return f"EX{datetime.now().strftime('%H%M%S')}{_msg_counter:03d}"
 
def envolver_mllp(mensagem):
    return MLLP_START + mensagem.encode("utf-8") + MLLP_END
 
def remover_mllp(dados):
    if dados.startswith(MLLP_START):
        dados = dados[1:]
    if dados.endswith(MLLP_END):
        dados = dados[:-2]
    return dados.decode("utf-8", errors="replace")
 
# ===============================
# CRIAÇÃO DE MENSAGENS HL7
# ===============================
 
def criar_cabecalho_msh(tipo_evento):
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
    msg_id = gerar_msg_id()
    return f"MSH|^~\\&|ProgramaA|Clinica|Mirth|Hospital|{agora}||{tipo_evento}|{msg_id}|P|2.5\r"
 
def criar_pid(pid, nome, dob, sexo):
    return f"PID|1||{pid}||{nome}||{dob}|{sexo}\r"
 
def criar_pv1(tipo_visita="O"):
    return f"PV1||{tipo_visita}|RAD\r"
 
def criar_orc(acao, order_id):
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"ORC|{acao}|{order_id}|{order_id}||||||{agora}\r"
 
def criar_obr(order_id, codigo_exame, desc_exame):
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"OBR|1|{order_id}|{order_id}|{codigo_exame}^{desc_exame}|{agora}\r"
 
def criar_pedido_novo(paciente, exame):
    order_id = gerar_order_id()
    msg  = criar_cabecalho_msh("ORM^O01")
    msg += criar_pid(paciente["pid"], paciente["nome"], paciente["dob"], paciente["sexo"])
    msg += criar_pv1()
    msg += criar_orc("NW", order_id)
    msg += criar_obr(order_id, exame["codigo"], exame["descricao"])
    return msg, order_id
 
def criar_cancelamento(paciente, exame, order_id):
    msg  = criar_cabecalho_msh("ORM^O01")
    msg += criar_pid(paciente["pid"], paciente["nome"], paciente["dob"], paciente["sexo"])
    msg += criar_pv1()
    msg += criar_orc("CA", order_id)
    msg += criar_obr(order_id, exame["codigo"], exame["descricao"])
    return msg
 
def criar_pedido_analises(paciente, analise):
    order_id = gerar_order_id()
    msg  = criar_cabecalho_msh("OML^O21")
    msg += criar_pid(paciente["pid"], paciente["nome"], paciente["dob"], paciente["sexo"])
    msg += criar_pv1("URG")
    msg += criar_orc("NW", order_id)
    msg += criar_obr(order_id, analise["codigo"], analise["descricao"])
    return msg, order_id
 
def criar_admissao(paciente, tipo_visita="I"):
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
    msg_id = gerar_msg_id()
    msg  = f"MSH|^~\\&|ProgramaA|Clinica|Mirth|Hospital|{agora}||ADT^A01|{msg_id}|P|2.5\r"
    msg += f"EVN|A01|{agora}\r"
    msg += criar_pid(paciente["pid"], paciente["nome"], paciente["dob"], paciente["sexo"])
    msg += f"PV1||{tipo_visita}|INT\r"
    return msg
 
# ===============================
# ENVIO / RECEÇÃO
# ===============================
 
def enviar_para_mirth(mensagem):
    pacote = envolver_mllp(mensagem)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as cliente:
            cliente.connect((MIRTH_HOST, MIRTH_PORTA_PEDIDO))
            cliente.sendall(pacote)
        return True
    except ConnectionRefusedError:
        print("\n  [ERRO] Não foi possível ligar ao Mirth. O canal está ativo?")
        return False
 
def escutar_relatorio():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as servidor:
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor.bind((HOST_LOCAL, PORTA_RELATORIO))
        servidor.listen(5)
        print(f"  [INFO] À espera de relatórios na porta {PORTA_RELATORIO}...\n")
        while True:
            conn, addr = servidor.accept()
            threading.Thread(target=tratar_relatorio, args=(conn, addr), daemon=True).start()
 
def tratar_relatorio(conn, addr):
    with conn:
        buffer = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk
            if MLLP_END in buffer:
                break
 
        mensagem = remover_mllp(buffer)
        order_id_encontrado = None
 
        if "ORU^R01" in mensagem:
            titulo = "RELATÓRIO DE RESULTADO RECEBIDO"
            for linha in mensagem.split("\r"):
                if linha.startswith("ORC"):
                    partes = linha.split("|")
                    if len(partes) > 2:
                        order_id_encontrado = partes[2]
 
            if order_id_encontrado:
                # Atualizar em memória
                if order_id_encontrado in pedidos_ativos:
                    pedidos_ativos[order_id_encontrado]["estado"] = "REALIZADO"
                # Atualizar na base de dados JSON
                atualizar_estado_pedido_db(order_id_encontrado, "REALIZADO", relatorio=mensagem)
 
        elif "ADT^A01" in mensagem:
            titulo = "CONFIRMAÇÃO DE ADMISSÃO RECEBIDA"
        else:
            titulo = "RESPOSTA RECEBIDA"
 
        print("\n" + "="*52)
        print(f"  {titulo}")
        print("="*52)
        print(mensagem)
        print("="*52 + "\n")
        print("  > ", end="", flush=True)
 
# Histórico de pedidos em memória (sessão atual)
pedidos_ativos = {}
 
# ===============================
# VALIDAÇÃO DE INPUT
# ===============================
 
def pedir_campo(prompt, validar, msg_erro, transformar=None):
    while True:
        valor = input(f"  {prompt}: ").strip()
        if validar(valor):
            return transformar(valor) if transformar else valor
        print(f"  [ERRO] {msg_erro}")
 
def validar_pid(v):
    return bool(re.fullmatch(r"\d{1,10}", v))
 
def validar_nome(v):
    return bool(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ\- ]{2,60}", v))
 
def validar_dob(v):
    if not re.fullmatch(r"\d{8}", v):
        return False
    try:
        datetime.strptime(v, "%Y%m%d")
        return True
    except ValueError:
        return False
 
def validar_sexo(v):
    return v.upper() in ("M", "F")
 
def validar_codigo(v):
    return bool(re.fullmatch(r"[A-Za-z0-9]{1,20}", v))
 
def validar_descricao(v):
    return len(v.strip()) >= 2
 
# ===============================
# GESTÃO DE PACIENTES
# ===============================
 
def registar_novo_paciente():
    """Regista um novo paciente na base de dados."""
    print("\n  REGISTAR NOVO PACIENTE")
    print("  ─────────────────────────────────────────")
 
    pid = pedir_campo(
        "PID — Nº processo (ex: 123456)",
        validar_pid,
        "PID inválido. Use apenas dígitos (máx. 10)."
    )
 
    # Verificar se já existe
    existente = obter_paciente_db(pid)
    if existente:
        print(f"\n  [AVISO] Já existe um paciente com PID {pid}:")
        print(f"  Nome: {existente['nome']}  |  DN: {existente['dob']}  |  Sexo: {existente['sexo']}")
        confirmar = input("  Deseja atualizar os dados? (S/N): ").strip().upper()
        if confirmar != "S":
            print("  Operação cancelada.")
            return None
 
    nome = pedir_campo(
        "Nome",
        validar_nome,
        "Nome inválido. Use apenas letras, espaços e hífens (mín. 2 caracteres)."
    )
    dob = pedir_campo(
        "Data de nascimento (YYYYMMDD, ex: 19900101)",
        validar_dob,
        "Data inválida. Use o formato YYYYMMDD (ex: 19850321)."
    )
    sexo = pedir_campo(
        "Sexo (M/F)",
        validar_sexo,
        "Sexo inválido. Introduza M ou F.",
        transformar=str.upper
    )
 
    paciente = {"pid": pid, "nome": nome, "dob": dob, "sexo": sexo}
    registar_paciente_db(paciente)
    print(f"\n  [OK] Paciente '{nome}' registado com sucesso (PID: {pid}).")
    return paciente
 
def listar_pacientes():
    """Lista todos os pacientes registados."""
    pacientes = listar_pacientes_db()
    print("\n  PACIENTES REGISTADOS")
    print("  ─────────────────────────────────────────")
    if not pacientes:
        print("  (nenhum paciente registado)")
    else:
        for pid, p in pacientes.items():
            print(f"  [{pid}]  {p['nome']}  |  DN: {p['dob']}  |  Sexo: {p['sexo']}")
    print(f"\n  Total: {len(pacientes)} paciente(s)")
 
def selecionar_paciente():
    """Pede o PID e devolve os dados do paciente. Só aceita pacientes existentes."""
    listar_pacientes()
    pacientes = listar_pacientes_db()
    if not pacientes:
        print("\n  [ERRO] Não existem pacientes registados.")
        print("  Use a opção [6] para registar um novo paciente.")
        return None
 
    print()
    pid = pedir_campo(
        "Introduza o PID do paciente",
        validar_pid,
        "PID inválido. Use apenas dígitos (máx. 10)."
    )
 
    paciente = obter_paciente_db(pid)
    if not paciente:
        print(f"\n  [ERRO] Paciente com PID '{pid}' não encontrado.")
        print("  Só é possível criar pedidos para pacientes registados.")
        print("  Use a opção [6] para registar um novo paciente.")
        return None
 
    print(f"\n  Paciente selecionado: {paciente['nome']} (PID: {pid})")
    return paciente
 
def ver_pedidos_por_paciente():
    """Mostra todos os pedidos de um paciente específico."""
    listar_pacientes()
    pacientes = listar_pacientes_db()
    if not pacientes:
        print("\n  (nenhum paciente registado)")
        return
 
    pid = pedir_campo(
        "\n  Introduza o PID do paciente",
        validar_pid,
        "PID inválido."
    )
 
    paciente = obter_paciente_db(pid)
    if not paciente:
        print(f"  [ERRO] Paciente com PID '{pid}' não encontrado.")
        return
 
    pedidos = pedidos_por_paciente_db(pid)
    print(f"\n  PEDIDOS DE {paciente['nome'].upper()} (PID: {pid})")
    print("  ─────────────────────────────────────────")
 
    if not pedidos:
        print("  (nenhum pedido registado para este paciente)")
    else:
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
 
            # Mostrar relatório se existir
            if estado == "REALIZADO" and p.get("relatorio"):
                ver_rel = input("    Ver relatório completo? (S/N): ").strip().upper()
                if ver_rel == "S":
                    print("  ┌─ RELATÓRIO HL7 " + "─"*35)
                    for linha in p["relatorio"].strip().split("\r"):
                        print(f"  │ {linha}")
                    print("  └" + "─"*51)
 
# ===============================
# INTRODUÇÃO DE DADOS
# ===============================
 
def introduzir_exame_imagiologia():
    exames_disponiveis = {
        "1": {"codigo": "M10405", "descricao": "TORAX, UMA INCIDENCIA"},
        "2": {"codigo": "TAC01",  "descricao": "TAC ABDOMINAL"},
        "3": {"codigo": "ECO02",  "descricao": "ECOGRAFIA RENAL"},
        "4": {"codigo": "M10",    "descricao": "MAMOGRAFIA BILATERAL"},
    }
    print("\n  Selecione o Exame")
    for tecla, info in exames_disponiveis.items():
        print(f"  [{tecla}] {info['descricao']} ({info['codigo']})")
    opcao = pedir_campo(
        "Opção",
        lambda v: v in exames_disponiveis,
        "Opção inválida. Escolha um número da lista."
    )
    return exames_disponiveis[opcao]
 
def introduzir_analise():
    analises_disponiveis = {
        "1": {"codigo": "25826", "descricao": "Ureia"},
        "2": {"codigo": "25813", "descricao": "Potassio"},
        "3": {"codigo": "HEM01", "descricao": "Hemoglobina"},
        "4": {"codigo": "60996", "descricao": "Estudo bacteriologico"},
    }
    print("\n  SELECIONE A ANÁLISE CLÍNICA")
    print("  ─────────────────────────────────────────")
    for tecla, info in analises_disponiveis.items():
        print(f"  [{tecla}] {info['descricao']} ({info['codigo']})")
    opcao = pedir_campo(
        "Opção",
        lambda v: v in analises_disponiveis,
        "Opção inválida. Escolha um número da lista."
    )
    return analises_disponiveis[opcao]
 
# ===============================
# MENUS E UTILITÁRIOS
# ===============================
 
def limpar():
    print("\033[2J\033[H", end="")
 
def cabecalho():
    print("        SISTEMA DE PEDIDOS DE EXAMES MÉDICOS          ")
    print("              Programa A  —  Cliente HL7               ")
    print()
 
def menu_principal():
    print("  MENU PRINCIPAL")
    print("  [1] Novo pedido de exame (imagiologia)")
    print("  [2] Novo pedido de análises clínicas")
    print("  [3] Cancelar pedido existente")
    print("  [4] Registar admissão de doente")
    print("  [5] Ver histórico de pedidos")
    print("  [6] Registar novo paciente")
    print("  [7] Listar pacientes")
    print("  [8] Ver pedidos por paciente")
    print("  [0] Sair")
    return input("  Opção: ").strip()
 
def mostrar_mensagem_hl7(mensagem, titulo="MENSAGEM HL7 ENVIADA"):
    print(f"\n  ┌─ {titulo} {'─'*(44-len(titulo))}")
    for linha in mensagem.strip().split("\r"):
        print(f"  │ {linha}")
    print(f"  └{'─'*50}")
 
def ver_pedidos_ativos():
    """Mostra pedidos da sessão atual + todos os pedidos da base de dados."""
    print("\n  HISTÓRICO COMPLETO DE PEDIDOS")
    print("  ─────────────────────────────────────────")
    db = carregar_db()
    pedidos = db.get("pedidos", {})
 
    if not pedidos:
        print("  (nenhum pedido registado)")
    else:
        for oid, info in pedidos.items():
            nome   = info.get("nome_paciente", "?")
            tipo   = info.get("tipo", "?")
            exame  = info.get("exame", {})
            desc   = exame.get("descricao", "?") if isinstance(exame, dict) else str(exame)
            estado = info.get("estado", "?")
            print(f"  [{oid}]  {nome}  —  {tipo}  —  {desc}  —  {estado}")
 
# ===============================
# AÇÕES
# ===============================
 
def acao_novo_exame_imagiologia():
    paciente = selecionar_paciente()
    if not paciente:
        return
 
    exame = introduzir_exame_imagiologia()
    mensagem, order_id = criar_pedido_novo(paciente, exame)
    mostrar_mensagem_hl7(mensagem)
    input("\n  Prima Enter para enviar...")
    if enviar_para_mirth(mensagem):
        pedidos_ativos[order_id] = {
            "paciente": paciente,
            "exame": exame,
            "tipo": "Imagiologia",
            "estado": "PENDENTE",
            "enviado_em": datetime.now(),
        }
        registar_pedido_db(order_id, paciente, "Imagiologia", exame)
        print(f"\n  [OK] Pedido enviado! Order ID: {order_id}")
        print(f"  [INFO] Pode cancelar o pedido com a opção [3].")
 
def acao_novo_pedido_analises():
    paciente = selecionar_paciente()
    if not paciente:
        return
 
    analise = introduzir_analise()
    mensagem, order_id = criar_pedido_analises(paciente, analise)
    mostrar_mensagem_hl7(mensagem)
    input("\n  Prima Enter para enviar...")
    if enviar_para_mirth(mensagem):
        pedidos_ativos[order_id] = {
            "paciente": paciente,
            "analise": analise,
            "tipo": "Análises",
            "estado": "PENDENTE",
            "enviado_em": datetime.now(),
        }
        registar_pedido_db(order_id, paciente, "Análises", analise)
        print(f"\n  [OK] Pedido enviado! Order ID: {order_id}")
        print(f"  [INFO] Pode cancelar o pedido com a opção [3].")
 
def acao_cancelar_pedido():
    ver_pedidos_ativos()
    db = carregar_db()
    pedidos = db.get("pedidos", {})
    if not pedidos:
        return
 
    order_id = input("\n  Introduza o Order ID a cancelar: ").strip().strip("[]")
 
    # Verificar no DB
    info_db = pedidos.get(order_id)
    if not info_db:
        print("  [ERRO] Order ID não encontrado.")
        return
 
    estado = info_db.get("estado", "PENDENTE")
    if estado == "REALIZADO":
        print("  [ERRO] Este exame já foi realizado. Não é possível cancelar.")
        return
    if estado == "CANCELADO":
        print("  [AVISO] Este pedido já foi cancelado anteriormente.")
        return
 
    # Reconstruir dados para criar a mensagem HL7
    pid = info_db.get("pid")
    paciente = obter_paciente_db(pid)
    if not paciente:
        print("  [ERRO] Dados do paciente não encontrados.")
        return
 
    exame = info_db.get("exame", {})
    mensagem = criar_cancelamento(paciente, exame, order_id)
    mostrar_mensagem_hl7(mensagem, titulo="CANCELAMENTO HL7")
    input("\n  Prima Enter para enviar o cancelamento...")
 
    if enviar_para_mirth(mensagem):
        # Atualizar em memória
        if order_id in pedidos_ativos:
            pedidos_ativos[order_id]["estado"] = "CANCELADO"
        # Atualizar na base de dados
        atualizar_estado_pedido_db(order_id, "CANCELADO")
        print(f"\n  [OK] Pedido {order_id} cancelado com sucesso!")
        print("  [INFO] Nenhum relatório será gerado para este pedido.")
 
def acao_admissao():
    paciente = selecionar_paciente()
    if not paciente:
        return
 
    print("\n  Tipo de visita:")
    print("  [I] Internamento   [O] Ambulatório   [U] Urgência")
    tipo = pedir_campo(
        "Opção (I/O/U)",
        lambda v: v.upper() in ("I", "O", "U"),
        "Opção inválida. Introduza I, O ou U.",
        transformar=str.upper
    )
    tipo_map = {"I": "I", "O": "O", "U": "URG"}
    tv = tipo_map[tipo]
 
    mensagem = criar_admissao(paciente, tv)
    mostrar_mensagem_hl7(mensagem, titulo="ADMISSÃO HL7 (ADT^A01)")
    input("\n  Prima Enter para enviar...")
    if enviar_para_mirth(mensagem):
        print(f"\n  [OK] Admissão registada com sucesso!")
 
# ===============================
# MAIN
# ===============================
 
if __name__ == "__main__":
    limpar()
    cabecalho()
 
    thread_rel = threading.Thread(target=escutar_relatorio, daemon=True)
    thread_rel.start()
    time.sleep(0.5)
 
    # Mostrar resumo de pacientes registados ao arrancar
    pacientes = listar_pacientes_db()
    print(f"  Base de dados carregada: {len(pacientes)} paciente(s) registado(s).")
    if pacientes:
        print("  Use a opção [7] para ver a lista de pacientes.\n")
    else:
        print("  Use a opção [6] para registar o primeiro paciente.\n")
 
    while True:
        print()
        cabecalho()
        opcao = menu_principal()
 
        if opcao == "1":
            acao_novo_exame_imagiologia()
        elif opcao == "2":
            acao_novo_pedido_analises()
        elif opcao == "3":
            acao_cancelar_pedido()
        elif opcao == "4":
            acao_admissao()
        elif opcao == "5":
            ver_pedidos_ativos()
        elif opcao == "6":
            registar_novo_paciente()
        elif opcao == "7":
            listar_pacientes()
        elif opcao == "8":
            ver_pedidos_por_paciente()
        elif opcao == "0":
            print("\n  A sair... Até logo!\n")
            break
        else:
            print("\n  Opção inválida. Tente novamente.")
 
        input("\n  Prima Enter para voltar ao menu...")
 