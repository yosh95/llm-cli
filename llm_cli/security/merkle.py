import hashlib


class MerkleTree:
    """
    A Merkle Tree implementation for session-wide audit anchoring.
    Provides a compact root hash and verifiable proofs for individual log entries.
    """

    def __init__(self, leaf_hashes: list[str]):
        if not leaf_hashes:
            raise ValueError("Cannot create a Merkle Tree with no leaves.")

        self.leaves = [bytes.fromhex(h) if isinstance(h, str) else h for h in leaf_hashes]
        self.tree = self._build_tree(self.leaves)

    def _hash_pair(self, left: bytes, right: bytes) -> bytes:
        """Hash two child nodes together."""
        return hashlib.sha256(left + right).digest()

    def _build_tree(self, leaves: list[bytes]) -> list[list[bytes]]:
        """Build the Merkle Tree levels from leaves to root."""
        tree = [leaves]
        current_level = leaves

        while len(current_level) > 1:
            next_level = []
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                # If odd number of nodes, duplicate the last one
                right = current_level[i + 1] if i + 1 < len(current_level) else current_level[i]
                next_level.append(self._hash_pair(left, right))
            tree.append(next_level)
            current_level = next_level

        return tree

    @property
    def root(self) -> bytes:
        """Returns the Merkle Root hash."""
        return self.tree[-1][0]

    @property
    def root_hex(self) -> str:
        """Returns the hex string of the Merkle Root."""
        return self.root.hex()

    def get_proof(self, index: int) -> list[dict]:
        """
        Generates a Merkle Proof for the leaf at the given index.
        Each element in the proof contains the hash and its position (left/right).
        """
        if index < 0 or index >= len(self.leaves):
            raise IndexError("Leaf index out of range.")

        proof = []
        for level in range(len(self.tree) - 1):
            level_len = len(self.tree[level])
            if index % 2 == 1:
                # Leaf is a right child, sibling is to the left
                proof.append({"position": "left", "hash": self.tree[level][index - 1].hex()})
            else:
                # Leaf is a left child, sibling is to the right (if exists)
                if index + 1 < level_len:
                    proof.append({"position": "right", "hash": self.tree[level][index + 1].hex()})
                else:
                    # Duplicate sibling for odd number of nodes
                    proof.append({"position": "right", "hash": self.tree[level][index].hex()})

            index //= 2

        return proof

    @staticmethod
    def verify_proof(leaf_hash: str, proof: list[dict], root_hash: str) -> bool:
        """
        Verifies a Merkle Proof against a known root hash.
        """
        current_hash = bytes.fromhex(leaf_hash)

        for step in proof:
            sibling_hash = bytes.fromhex(step["hash"])
            if step["position"] == "left":
                current_hash = hashlib.sha256(sibling_hash + current_hash).digest()
            else:
                current_hash = hashlib.sha256(current_hash + sibling_hash).digest()

        return current_hash.hex() == root_hash
