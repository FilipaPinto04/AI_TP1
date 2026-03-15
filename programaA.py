import socket

def criar_mensagem_hl7():
    # Estrutura básica de uma mensagem de pedido (ORM)
    # MSH: Cabeçalho | PID: Identificação do Paciente | ORC: Commando do Pedido | OBR: Detalhes do Exame
    msh = "MSH|^~\\&|ProgA|HOSPITAL|MIRTH|SISTEMA|202603142100||ORM^O01|101|P|2.5"
    pid = "PID|1||12345^^^MRN||SILVA^JOAO||19850520|M"
    orc = "ORC|NW|A001|||||^^^^^R" 
    obr = "OBR|1|A001||RAD01^RAIO-X TORAX|||202603142100"
    
    # O protocolo MLLP requer os caracteres de controlo: <VT> (0x0b) no início e <FS><CR> (0x1c 0x0d) no fim
    return f"\x0b{msh}\r{pid}\r{orc}\r{obr}\r\x1c\r"

def enviar_pedido(host='127.0.0.1', porta=6661):
    msg = criar_mensagem_hl7()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, porta))
        s.sendall(msg.encode('utf-8'))
        resposta = s.recv(4096)
        print("Resposta recebida do Mirth:", resposta.decode('utf-8'))

if __name__ == "__main__":
    enviar_pedido()