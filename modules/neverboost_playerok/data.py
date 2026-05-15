import os
from data import Data as data, DataFile

PENDING_INVITES = DataFile(
    name="pending_invites",
    path=os.path.join(os.path.dirname(__file__), "module_data", "pending_invites.json"),
    default={}
)

SALES = DataFile(
    name="sales",
    path=os.path.join(os.path.dirname(__file__), "module_data", "sales.json"),
    default=[]
)

DATA = [PENDING_INVITES, SALES]


class Data:
    @staticmethod
    def get(name: str):
        return data.get(name, DATA)

    @staticmethod
    def set(name: str, new):
        return data.set(name, new, DATA)
