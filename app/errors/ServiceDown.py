class ServiceDown(Exception):
    def __init__(self, message="El servicio de la DGT parece estar caído, no responde correctamente o se ha superado el límite de peticiones ."):
        self.message = message
        super().__init__(self.message)