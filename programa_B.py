import socket
from datetime import datetime

# CONFIGURAÇÃO DO SERVIDOR LOCAL
HOST_LOCAL = "127.0.0.1"
PORTA_RECEBER_PEDIDO = 6000 # Onde o Mirth vai entregar o pedido

# CONFIGURAÇÃO DE LIGAÇÃO AO MIRTH
MIRTH_HOST = "127.0.0.1"
MIRTH_PORTA_RELATORIO = 5101 # Porta de entrada do Canal de Relatórios no Mirth

# CONSTANTES MLLP
MLLP_START = b"\x0b"
MLLP_END = b"\x1c\x0d"

def envolver_mllp(mensagem):
    return MLLP_START + mensagem.encode("utf-8") + MLLP_END

def remover_mllp(dados):
    if dados.startswith(MLLP_START):
        dados = dados[1:]
    if dados.endswith(MLLP_END):
        dados = dados[:-2]
    return dados.decode("utf-8", errors="replace")

def extrair_campo(segmento, indice):
    partes = segmento.split("|")
    return partes[indice] if len(partes) > indice else ""

def processar_pedido_hl7(mensagem):
    # Separa por carriage return (\r) como definido no Programa A
    linhas = mensagem.strip().split("\r")
    pid = ""
    nome = ""
    exame = ""

    for linha in linhas:
        # CORREÇÃO: startswith (com 't')
        if linha.startswith("PID"):
            pid = extrair_campo(linha, 3) 
            nome = extrair_campo(linha, 5)
        elif linha.startswith("OBR"):
            exame = extrair_campo(linha, 4)

    return pid, nome, exame

def criar_relatorio_hl7(pid, nome, exame):
    agora = datetime.now().strftime("%Y%m%d%H%M%S")
    # Gera mensagem ORU^R01 (Observational Report Unsolicited)
    return (
        f"MSH|^~\\&|ProgramaB|Laboratorio|Mirth|Clinica|{agora}||ORU^R01|RPT001|P|2.3\r"
        f"PID|1||{pid}||{nome}||19800101|M\r"
        f"OBR|1||EX001|{exame}|{agora}\r"
        f"OBX|1|TX|RESULTADO||Exame realizado com sucesso. Valores normais.|N\r"
    )

def enviar_relatorio_para_mirth(relatorio):
    pacote = envolver_mllp(relatorio)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as cliente:
            cliente.connect((MIRTH_HOST, MIRTH_PORTA_RELATORIO))
            cliente.sendall(pacote)
            print("Relatorio enviado para o Mirth com sucesso.\n")
    except ConnectionRefusedError:
        print("Erro: Não foi possível ligar ao Mirth. O canal está ativo?")

def iniciar_programa_b():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as servidor:
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor.bind((HOST_LOCAL, PORTA_RECEBER_PEDIDO))
        servidor.listen(1)
        
        print(f"Programa B (Laboratório) à escuta na porta {PORTA_RECEBER_PEDIDO}...")
        
        while True: # Mantém o programa aberto para vários pedidos
            conn, addr = servidor.accept()
            with conn:
                print(f"Ligação recebida de {addr}")
                buffer = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk: break
                    buffer += chunk
                    if MLLP_END in buffer: break
                
                dados = remover_mllp(buffer)
                print("\n====== Pedido HL7 Recebido =======")
                print(dados)
                
                pid, nome, exame = processar_pedido_hl7(dados)
                relatorio = criar_relatorio_hl7(pid, nome, exame)
                
                print("\n====== Relatório HL7 Gerado =======")
                print(relatorio)
                
                enviar_relatorio_para_mirth(relatorio)
                print("-" * 40)

if __name__ == "__main__":
    iniciar_programa_b()