import socket
import threading
import time
import random
from datetime import datetime

# ===============================
# CONFIGURAÇÃO
# ===============================
HOST_LOCAL = "127.0.0.1"
PORTA_RECEBER_PEDIDO = 6000

MIRTH_HOST = "127.0.0.1"
MIRTH_PORTA_RELATORIO = 5101

MLLP_START = b"\x0b"
MLLP_END = b"\x1c\x0d"

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
    """Extrai informação relevante de uma mensagem HL7."""
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
            # O Mirth está a concatenar campos. Vamos garantir que pegamos no tipo correto.
            msh_9 = extrair_campo(seg, 8)
            # Se o campo contiver um pipe ou for apenas o ID, tentamos limpar
            if "|" in msh_9:
                info["tipo_msg"] = msh_9.split("|")[0]
            else:
                info["tipo_msg"] = msh_9
            
            # Debug para veres o que está a ser lido (podes apagar depois)
            print(f"DEBUG: Tipo lido: {info['tipo_msg']}")

        elif tipo == "PID":
            info["pid"]   = extrair_campo(seg, 3)
            info["nome"]  = extrair_campo(seg, 5)
            info["dob"]   = extrair_campo(seg, 7)
            info["sexo"]  = extrair_campo(seg, 8)

        elif tipo == "PV1":
            info["tipo_visita"] = extrair_campo(seg, 2)

        elif tipo == "ORC":
            info["acao_orc"]  = extrair_campo(seg, 1)
            info["order_id"]  = extrair_campo(seg, 2)

        elif tipo == "OBR":
            info["order_id"]    = extrair_campo(seg, 2) or info["order_id"]
            exame_full          = extrair_campo(seg, 4)
            partes_exame        = exame_full.split("^")
            info["codigo_exame"] = partes_exame[0]
            info["desc_exame"]  = partes_exame[1] if len(partes_exame) > 1 else exame_full

    return info

# ===============================
# GERAÇÃO DE RELATÓRIOS HL7
# ===============================

def gerar_resultado_simulado(codigo_exame, desc_exame, tipo_msg):
    """Gera resultados simulados dependendo do tipo de exame."""
    agora = datetime.now().strftime("%Y%m%d%H%M%S")

    # Análises laboratoriais
    if "OML" in tipo_msg or any(c in codigo_exame for c in ["258", "609", "HEM"]):
        resultados_lab = {
            "25826": ("Ureia", "42", "mg/dL", "10-50"),
            "25813": ("Potassio", "4.1", "mmol/L", "3.5-5.0"),
            "HEM01": ("Hemoglobina", "13.5", "g/dL", "12.0-16.0"),
            "60996": ("Estudo bacteriologico", "Negativo", "", "Negativo"),
        }
        resultado = resultados_lab.get(codigo_exame, (desc_exame, str(round(random.uniform(3,10),1)), "U", "N/A"))
        nome_r, valor, unidade, ref = resultado
        obx_lines = (
            f"OBX|1|NM|{codigo_exame}^{nome_r}||{valor}|{unidade}|{ref}|N|||F|||{agora}\r"
        )
        return obx_lines, "Resultado laboratorial dentro dos valores de referência."

    # Imagiologia / Radiologia
    elif any(c in codigo_exame for c in ["M10", "TAC", "ECO"]):
        descricoes = [
            "Sem alterações significativas. Estruturas anatómicas preservadas.",
            "Exame realizado com sucesso. Sem lesões agudas identificadas.",
            "Imagem compatível com variante da normalidade. Sem sinais de patologia aguda.",
        ]
        texto = random.choice(descricoes)
        obx_lines = (
            f"OBX|1|TX|RESULTADO||{texto}||||||F|||{agora}\r"
            f"OBX|2|TX|CONCLUSAO||Exame validado pelo especialista.||||||F|||{agora}\r"
        )
        return obx_lines, texto

    else:
        obx_lines = f"OBX|1|TX|RESULTADO||Exame realizado com sucesso. Valores dentro da normalidade.||||||F|||{agora}\r"
        return obx_lines, "Exame realizado com sucesso."

def criar_relatorio_hl7(info):
    """Cria mensagem ORU^R01 de relatório final."""
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

def criar_ack_cancelamento(info):
    """Cria ACK de confirmação de cancelamento."""
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
    order_id = info["order_id"] or "EX000"

    msg  = f"MSH|^~\\&|ProgramaB|Laboratorio|Mirth|Clinica|{agora}||ORM^O01|ACK{agora}|P|2.5\r"
    msg += f"PID|1||{info['pid']}||{info['nome']}||{info['dob']}|{info['sexo']}\r"
    msg += f"ORC|CA|{order_id}|{order_id}||CA||||{agora}\r"
    msg += f"OBR|1|{order_id}|{order_id}|{info['codigo_exame']}^{info['desc_exame']}|{agora}\r"
    return msg

def criar_ack_admissao(info):
    """Cria confirmação de admissão."""
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
# PROCESSAMENTO DE PEDIDOS
# ===============================

# Estatísticas
stats = {"recebidos": 0, "enviados": 0, "cancelamentos": 0, "admissoes": 0, "erros": 0}

def processar_mensagem(dados_raw, addr):
    """Processa a mensagem recebida e decide que resposta enviar."""
    stats["recebidos"] += 1
    dados = remover_mllp(dados_raw)

    print("\n" + "─"*52)
    print(f"  [RECEBIDO] de {addr}")
    print("─"*52)
    print(dados)
    print("─"*52)

    info = parse_mensagem_hl7(dados)
    tipo_msg = info["tipo_msg"]
    acao     = info["acao_orc"]

    # Simula pequeno tempo de processamento
    time.sleep(0.5)

    resposta = None
    descricao = ""

    # --- Cancelamento ---
    if acao == "CA":
        stats["cancelamentos"] += 1
        resposta = criar_ack_cancelamento(info)
        descricao = f"Cancelamento confirmado para Order ID: {info['order_id']}"

    # --- Admissão ---
    elif "ADT" in tipo_msg:
        stats["admissoes"] += 1
        resposta = criar_ack_admissao(info)
        descricao = f"Admissão confirmada para: {info['nome']} (PID: {info['pid']})"

    # --- Pedido novo de exame ou análise ---
    elif acao in ("NW", "") and tipo_msg in ("ORM^O01", "OML^O21", ""):
        resposta = criar_relatorio_hl7(info)
        descricao = f"Relatório gerado para {info['nome']} — {info['desc_exame']}"
        stats["enviados"] += 1

    else:
        print(f"  [AVISO] Tipo de mensagem não reconhecido: tipo={tipo_msg}, acao={acao}")
        stats["erros"] += 1
        return

    if resposta:
        print(f"\n  [AÇÃO] {descricao}")
        print("\n  Resposta HL7 a enviar:")
        for linha in resposta.strip().split("\r"):
            print(f"  │ {linha}")
        if enviar_para_mirth(resposta):
            print(f"  [OK] Resposta enviada ao Mirth.\n")
        else:
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
# MENU PROGRAMA B
# ===============================

def cabecalho():
    print("    SISTEMA DE REALIZAÇÃO DE EXAMES — LABORATÓRIO     ")
    print("              Programa B  —  Servidor HL7              ")

def mostrar_stats():
    print("\n  ESTATÍSTICAS DE OPERAÇÃO")
    print("  ─────────────────────────────────────────")
    print(f"  Pedidos recebidos  : {stats['recebidos']}")
    print(f"  Relatórios enviados: {stats['enviados']}")
    print(f"  Cancelamentos      : {stats['cancelamentos']}")
    print(f"  Admissões          : {stats['admissoes']}")
    print(f"  Erros              : {stats['erros']}")
    print("  ─────────────────────────────────────────")

def menu_b():
    print("\n  MENU")
    print("  ─────────────────────────────────────────")
    print("  [1] Ver estatísticas")
    print("  [2] Testar envio de relatório manual")
    print("  [0] Parar servidor e sair")
    print("  ─────────────────────────────────────────")
    return input("  Opção: ").strip()

def teste_relatorio_manual():
    """Permite enviar um relatório de teste manualmente."""
    print("\n  RELATÓRIO DE TESTE")
    info_teste = {
        "tipo_msg": "ORM^O01",
        "pid": "999999",
        "nome": "Doente Teste",
        "dob": "19900101",
        "sexo": "M",
        "order_id": "TESTE001",
        "codigo_exame": "M10405",
        "desc_exame": "TORAX, UMA INCIDENCIA",
        "acao_orc": "NW",
        "tipo_visita": "O",
    }
    relatorio = criar_relatorio_hl7(info_teste)
    print("\n  Relatório a enviar:")
    for linha in relatorio.strip().split("\r"):
        print(f"  │ {linha}")
    input("\n  Prima Enter para enviar ao Mirth...")
    if enviar_para_mirth(relatorio):
        print("  [OK] Relatório de teste enviado!")
        stats["enviados"] += 1

# ===============================
# MAIN
# ===============================

if __name__ == "__main__":
    print("\033[2J\033[H", end="")
    cabecalho()

    # Iniciar servidor em thread separada
    t_servidor = threading.Thread(target=iniciar_servidor, daemon=True)
    t_servidor.start()
    time.sleep(0.5)

    print("\n  Servidor iniciado. À espera de pedidos do Mirth...\n")
    print("  Use o menu abaixo para gerir o servidor.\n")

    while True:
        opcao = menu_b()
        if opcao == "1":
            mostrar_stats()
        elif opcao == "2":
            teste_relatorio_manual()
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
