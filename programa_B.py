import socket
from datetime import datetime

#===============================
#CONFIGURAÇÃO DO SERVIDOR LOCAL
#===============================

# endereco ip local onde o programa B ira receber pedidos
HOST_LOCAL = "127.0.0.1"

# porta onde o programa B ficara a escuta para receber pedidos HL7
PORTA_RECEBER_PEDIDO = 6000

#===============================
# CONFIGURAÇÃO DE LIGAÇÃO AO MIRTH
#===============================

# enderco IP do mirth
MIRTH_HOST = "127.0.0.1"
MIRTH_PORTA_RELATORIO = 5101

#===============================
#CONSTANTES MLLP (protocolo HL7)
#===============================

# Byte de início da mensagem HL7 (MLLP Start Block)
MLLP_START = b"\x0b"

# Bytes de fim de mensagem HL7 (MLLP End Block)
MLLP_END = b"\x1c\x0d"

#==============================================
# FUNCAO PARA ENVOLVER MENSAGEM COM MLLP
#==============================================

def envolver_mllp(mensagem):
    # converte a mensagem para bytes e adiciona delimitadoras de MLLP
    return MLLP_START + mensagem.encode("utf-8") + MLLP_END

#==============================================
# FUNCAO PARA REMOVER MLLP DE UMA MENSAGEM
#==============================================

def remover_mllp(dados):
    # Se começar com byte de início, remove-o
    if dados.startswith(MLLP_START):
        dados = dados[1:]

    # Se terminar com bytes de fim, remove-os
    if dados.endswith(MLLP_END):
        dados = dados[:-2]

    #Converte bytes para string (UTF-8), substituindo erros
    return dados.decode("utf-8", errors="replace")

#==============================================
# FUNCAO auxiliar para extrari campos hl7
#==============================================

def extrair_campo(segmento, indice):
    # divide o segmento pelos separadores "|"
    partes = segmento.split("|")

    # devolver o campor pretendido se existir
    return partes[indice] if len(partes) > indice else ""

#==============================================
# FUNCAO para processar pedido hl7
#==============================================

def processar_pedido_hl7(mensagem):
    linhas = mensagem.strip().split("\r")

    pid=""
    nome=""
    exame = ""

    # percorre cada linha da mensagem
    for linha in linhas:

        #segmento pid (dados do paciente)
        if linha.starwith("PID"):
            pid = extrair_campo(linha, 3) # id do paciente
            nome = extrair_campo(linha, 5) # nome do paciente

        # segmento OBR (pedido de exame)
        elif linha.starwith("OBR"):
            exame = extrair_campo(linha, 4)

    return pid, nome, exame

#==============================================
# FUNCAO para criar relatorio hl7
#==============================================

def criar_relatorio_hl7(pid, nome, exame):
    agora = datetime.now().strftime("%Y%m%d%H%M%S")

    return (
        f"MSH|^~\\&|ProgramaB|Laboratorio|Mirth|Clinica|{agora}||ORU^R01|RPT001|P|2.3\r"
        f"PID|1||{pid}||{nome}||19800101|M\r"
        f"OBR|1||EX001|{exame}|{agora}\r"
        f"OBX|1|TX|RESULTADO||Exame realizado com sucesso. Valores dentro da normalidade. |N\r"
    )

#==============================================
# FUNCAO PARA ENVIAR RELATÓRIO para o mirth
#==============================================

def enviar_relatorio_para_mirth(relatorio):
    # envolve mensagem com mLLP
    pacote = envolver_mllp(relatorio)

    #Debug: mostra primeiros bytes enviados
    print("DEBUG bytes enviados para Mirth:", pacote[:10])

    # cria socket cliente TCP
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as cliente:

        # liga ao sesrvidor mirth
        cliente.connect((MIRTH_HOST, MIRTH_PORTA_RELATORIO))

        cliente.sendall(pacote)

    print("Relatorio enviado para o mirth com sucesso.\n")

#==============================================
# FUNCAO princiapl do pragram b
#==============================================
    
def iniciar_programa_b():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as servidor:
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        servidor.bind((HOST_LOCAL, PORTA_RECEBER_PEDIDO))

        servidor.listen(1)

        print(f"Programa B à escuta na porta {PORTA_RECEBER_PEDIDO}...")

        conn,addr = servidor.accept()

        with conn:
            print(f"Ligacao recebida de {addr}")

            buffer = b""

            while True:
                chunk = conn.recv(4096)

                if not chunk:
                    break

                buffer += chunk

                if MLLP_END in buffer:
                    break

            dados = remover_mllp(buffer)

            print("\n ====== Pedido hl7 recebido =======")
            print(dados)
            print("===========================================\n")

            pid, nome, exame = processar_pedido_hl7(dados)

            relatorio = criar_relatorio_hl7(pid, nome, exame)

            print("\n ====== relatorio hl7 recebido =======")
            print(relatorio)
            print("===========================================\n")

            enviar_relatorio_para_mirth(relatorio)

#==============================================
# Ponto de entrada do programa
#==============================================
    
if __name__ == "__main__":
    iniciar_programa_b()