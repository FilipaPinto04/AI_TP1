import socket
import threading
import time
from datetime import datetime

# ===============================
# CONFIGURAÇÃO
# ===============================
MIRTH_HOST = "127.0.0.1"
MIRTH_PORTA_PEDIDO = 5100

HOST_LOCAL = "127.0.0.1"
PORTA_RELATORIO = 6001

MLLP_START = b"\x0b"
MLLP_END = b"\x1c\x0d"

# Contador de mensagens para IDs únicos
_msg_counter = 0

def gerar_msg_id():
    global _msg_counter
    _msg_counter += 1
    return f"MSG{_msg_counter:04d}"

def gerar_order_id():
    return f"EX{datetime.now().strftime('%H%M%S')}{_msg_counter:03d}"

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
# CRIAÇÃO DE MENSAGENS HL7
# ===============================

def criar_cabecalho_msh(tipo_evento):
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
    msg_id = gerar_msg_id()
    # MSH-7 é data, MSH-8 é vazio, MSH-9 é tipo_evento, MSH-10 é msg_id
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

# ---- PEDIDO NOVO (NW) ----
def criar_pedido_novo(paciente, exame):
    order_id = gerar_order_id()
    msg  = criar_cabecalho_msh("ORM^O01")
    msg += criar_pid(paciente["pid"], paciente["nome"], paciente["dob"], paciente["sexo"])
    msg += criar_pv1()
    msg += criar_orc("NW", order_id)
    msg += criar_obr(order_id, exame["codigo"], exame["descricao"])
    return msg, order_id

# ---- CANCELAMENTO (CA) ----
def criar_cancelamento(paciente, exame, order_id):
    msg  = criar_cabecalho_msh("ORM^O01")
    msg += criar_pid(paciente["pid"], paciente["nome"], paciente["dob"], paciente["sexo"])
    msg += criar_pv1()
    msg += criar_orc("CA", order_id)
    msg += criar_obr(order_id, exame["codigo"], exame["descricao"])
    return msg

# ---- PEDIDO DE ANÁLISES (OML^O21) ----
def criar_pedido_analises(paciente, analise):
    order_id = gerar_order_id()
    msg  = criar_cabecalho_msh("OML^O21")
    msg += criar_pid(paciente["pid"], paciente["nome"], paciente["dob"], paciente["sexo"])
    msg += criar_pv1("URG")
    msg += criar_orc("NW", order_id)
    msg += criar_obr(order_id, analise["codigo"], analise["descricao"])
    return msg, order_id

# ---- ADMISSÃO (ADT^A01) ----
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
        print("\n" + "="*50)
        print("  RELATÓRIO RECEBIDO")
        print("="*50)
        print(remover_mllp(buffer))
        print("="*50 + "\n")
        print("  > ", end="", flush=True)

# Histórico de pedidos ativos (para cancelamentos)
pedidos_ativos = {}  # order_id -> {paciente, exame/analise, tipo}

# ===============================
# VALIDAÇÃO DE INPUT
# ===============================

import re

def pedir_campo(prompt, validar, msg_erro, transformar=None):
    """Pede um campo em loop até o valor ser válido."""
    while True:
        valor = input(f"  {prompt}: ").strip()
        if validar(valor):
            return transformar(valor) if transformar else valor
        print(f"  [ERRO] {msg_erro}")

def validar_pid(v):
    return bool(re.fullmatch(r"\d{1,10}", v))

def validar_nome(v):
    # Aceita letras (incluindo acentuadas), espaços e hífens; mínimo 2 chars
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

def introduzir_paciente():
    """Solicita os dados do paciente com validação em cada campo."""
    print("\n  DADOS DO PACIENTE")
    print("  ─────────────────────────────────────────")
    nome = pedir_campo(
        "Nome (ex: Maria Santos)",
        validar_nome,
        "Nome inválido. Use apenas letras, espaços e hífens (mín. 2 caracteres)."
    )
    pid = pedir_campo(
        "PID — Nº processo (ex: 123456)",
        validar_pid,
        "PID inválido. Use apenas dígitos (máx. 10)."
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
    return {"pid": pid, "nome": nome, "dob": dob, "sexo": sexo}

def introduzir_exame_imagiologia():
    """Solicita a seleção de um exame de imagiologia pré-definido."""
    exames_disponiveis = {
        "1": {"codigo": "M10405", "descricao": "TORAX, UMA INCIDENCIA"},
        "2": {"codigo": "TAC01",  "descricao": "TAC ABDOMINAL"},
        "3": {"codigo": "ECO02",  "descricao": "ECOGRAFIA RENAL"},
        "4": {"codigo": "M10",    "descricao": "MAMOGRAFIA BILATERAL"}
    }

    print("\n  SELECIONE O EXAME DE IMAGIOLOGIA")
    print("  ─────────────────────────────────────────")
    for tecla, info in exames_disponiveis.items():
        print(f"  [{tecla}] {info['descricao']} ({info['codigo']})")
    
    opcao = pedir_campo(
        "Opção",
        lambda v: v in exames_disponiveis.keys(),
        "Opção inválida. Escolha um número da lista."
    )
    
    return exames_disponiveis[opcao]

def introduzir_analise():
    """Solicita a seleção de uma análise clínica pré-definida."""
    analises_disponiveis = {
        "1": {"codigo": "25826", "descricao": "Ureia"},
        "2": {"codigo": "25813", "descricao": "Potassio"},
        "3": {"codigo": "HEM01", "descricao": "Hemoglobina"},
        "4": {"codigo": "60996", "descricao": "Estudo bacteriologico"}
    }

    print("\n  SELECIONE A ANÁLISE CLÍNICA")
    print("  ─────────────────────────────────────────")
    for tecla, info in analises_disponiveis.items():
        print(f"  [{tecla}] {info['descricao']} ({info['codigo']})")
    
    opcao = pedir_campo(
        "Opção",
        lambda v: v in analises_disponiveis.keys(),
        "Opção inválida. Escolha um número da lista."
    )
    
    return analises_disponiveis[opcao]

# ===============================
# MENUS
# ===============================

def limpar():
    print("\033[2J\033[H", end="")

def cabecalho():
    print("        SISTEMA DE PEDIDOS DE EXAMES MÉDICOS          ")
    print("              Programa A  —  Cliente HL7               ")
    print()

def menu_principal():
    print("  MENU PRINCIPAL")
    print("  ─────────────────────────────────────────")
    print("  [1] Novo pedido de exame (imagiologia)")
    print("  [2] Novo pedido de análises clínicas")
    print("  [3] Cancelar pedido existente")
    print("  [4] Registar admissão de doente")
    print("  [5] Ver histórico de pedidos ativos")
    print("  [0] Sair")
    print("  ─────────────────────────────────────────")
    return input("  Opção: ").strip()

def mostrar_mensagem_hl7(mensagem, titulo="MENSAGEM HL7 ENVIADA"):
    print(f"\n  ┌─ {titulo} {'─'*(44-len(titulo))}")
    for linha in mensagem.strip().split("\r"):
        print(f"  │ {linha}")
    print(f"  └{'─'*50}")

def ver_pedidos_ativos():
    print("\n  PEDIDOS ATIVOS")
    print("  ─────────────────────────────────────────")
    if not pedidos_ativos:
        print("  (nenhum pedido ativo)")
    else:
        for oid, info in pedidos_ativos.items():
            pac = info["paciente"]["nome"]
            tipo = info["tipo"]
            desc = info.get("exame", info.get("analise", {})).get("descricao", "?")
            print(f"  [{oid}]  {pac}  —  {tipo}  —  {desc}")
    print("  ─────────────────────────────────────────")

# ===============================
# AÇÕES
# ===============================

def acao_novo_exame_imagiologia():
    paciente = introduzir_paciente()
    exame = introduzir_exame_imagiologia()

    mensagem, order_id = criar_pedido_novo(paciente, exame)
    mostrar_mensagem_hl7(mensagem)
    input("\n  Prima Enter para enviar...")
    if enviar_para_mirth(mensagem):
        pedidos_ativos[order_id] = {"paciente": paciente, "exame": exame, "tipo": "Imagiologia"}
        print(f"\n  [OK] Pedido enviado com sucesso! Order ID: {order_id}")

def acao_novo_pedido_analises():
    paciente = introduzir_paciente()
    analise = introduzir_analise()

    mensagem, order_id = criar_pedido_analises(paciente, analise)
    mostrar_mensagem_hl7(mensagem)
    input("\n  Prima Enter para enviar...")
    if enviar_para_mirth(mensagem):
        pedidos_ativos[order_id] = {"paciente": paciente, "analise": analise, "tipo": "Análises"}
        print(f"\n  [OK] Pedido enviado com sucesso! Order ID: {order_id}")

def acao_cancelar_pedido():
    ver_pedidos_ativos()
    if not pedidos_ativos:
        return
    order_id = input("\n  Introduza o Order ID a cancelar: ").strip()
    if order_id not in pedidos_ativos:
        print("  [ERRO] Order ID não encontrado.")
        return

    info = pedidos_ativos[order_id]
    paciente = info["paciente"]
    exame = info.get("exame", info.get("analise"))

    mensagem = criar_cancelamento(paciente, exame, order_id)
    mostrar_mensagem_hl7(mensagem, titulo="CANCELAMENTO HL7")
    input("\n  Prima Enter para enviar o cancelamento...")
    if enviar_para_mirth(mensagem):
        del pedidos_ativos[order_id]
        print(f"\n  [OK] Pedido {order_id} cancelado com sucesso!")

def acao_admissao():
    paciente = introduzir_paciente()
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

    # Iniciar thread de escuta de relatórios
    thread_rel = threading.Thread(target=escutar_relatorio, daemon=True)
    thread_rel.start()
    time.sleep(0.5)

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
        elif opcao == "0":
            print("\n  A sair... Até logo!\n")
            break
        else:
            print("\n  Opção inválida. Tente novamente.")

        input("\n  Prima Enter para voltar ao menu...")
