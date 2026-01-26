from abc import ABC, abstractmethod

class Packet(ABC):
    @abstractmethod
    def serialize(self) -> bytes:
        pass