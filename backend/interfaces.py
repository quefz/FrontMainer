import abc

class ITransaction(abc.ABC):
    @abc.abstractmethod
    def to_dict(self) -> dict:
        pass

    @abc.abstractmethod
    def get_tx_id(self) -> str:
        pass

class IBlock(abc.ABC):
    def __init__(self, index: int, prev_hash: str, transactions: list, difficulty: int = 3):
        self.index = index
        self.prev_hash = prev_hash
        self.transactions = transactions
        self.difficulty = difficulty
        self.nonce = 0
        self.hash = None

    @abc.abstractmethod
    def calculate_hash(self) -> str:
        pass

    @abc.abstractmethod
    def mine(self):
        pass

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "transactions": self.transactions,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
            "hash": self.hash,
        }