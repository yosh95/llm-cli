import argparse
import json
import sys
from pathlib import Path

from llm_cli.security.identity import IdentityManager
from llm_cli.security.pqc import SecureStorage


def decrypt_log_file(input_path: Path, output_path: Path | None = None) -> None:
    """
    Decrypts ML-KEM encrypted entries in an audit log file.
    """
    if not input_path.exists():
        print(f"Error: File {input_path} not found.")
        sys.exit(1)

    # Load the private key for decryption
    try:
        priv_kem = IdentityManager._get_kem_private_key_content()
    except Exception as e:
        print(f"Error: Failed to load PQC private key: {e}")
        sys.exit(1)

    decrypted_entries = []
    with input_path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            try:
                entry = json.loads(line)
                if entry.get("pqc_confidential") is True:
                    encrypted_packet = entry["args"]
                    decrypted_bytes = SecureStorage.decrypt(encrypted_packet, priv_kem)
                    entry["args"] = json.loads(decrypted_bytes.decode())
                    entry["pqc_confidential"] = "DECRYPTED"

                decrypted_entries.append(entry)
            except Exception as e:
                print(f"Warning: Failed to process line {i + 1}: {e}")
                decrypted_entries.append(
                    {"error": f"Decryption failed: {str(e)}", "raw": line}
                )

    if output_path:
        with output_path.open("w", encoding="utf-8") as f:
            for entry in decrypted_entries:
                f.write(json.dumps(entry) + "\n")
        print(
            f"Successfully decrypted {len(decrypted_entries)} entries to {output_path}"
        )
    else:
        # Print to stdout
        for entry in decrypted_entries:
            print(json.dumps(entry, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="PQC Log Decryption Tool (ML-KEM)")
    parser.add_argument("input", help="Path to the encrypted audit log (.jsonl)")
    parser.add_argument("-o", "--output", help="Path to save the decrypted log")

    args = parser.parse_args()
    decrypt_log_file(Path(args.input), Path(args.output) if args.output else None)


if __name__ == "__main__":
    main()
