class ServiceDown(Exception):
    def __init__(
        self,
        message="The DGT service appears to be down, is not responding correctly, "
                "or the rate limit has been exceeded.",
    ):
        self.message = message
        super().__init__(self.message)
