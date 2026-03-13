import argparse
import logging
import sys
from pathlib import Path

from llm_cli.security.identity import IdentityManager
from llm_cli.security.integrity import IntegrityVerifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM-CLI Identity and Integrity Management Tool"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # keygen command
    subparsers.add_parser("keygen", help="Generate RSA and PQC key pairs")

    # manifest command
    subparsers.add_parser("manifest", help="Generate/Update integrity manifest")

    # decrypt-log command
    decrypt_parser = subparsers.add_parser(
        "decrypt-log", help="Decrypt PQC-encrypted (ML-KEM) audit logs"
    )
    decrypt_parser.add_argument(
        "input", help="Path to the encrypted audit log (.jsonl)"
    )
    decrypt_parser.add_argument("-o", "--output", help="Path to save the decrypted log")

    args = parser.parse_args()

    if args.command == "keygen":
        print("🛡️  Generating Identity Keys...")
        IdentityManager._ensure_keys(force=True)
        print(f"✅ Keys generated in {IdentityManager._KEY_DIR}")
        print(
            f"RSA Public Key: {IdentityManager._PRIVATE_KEY_PATH.with_suffix('.pub')}"
        )
        print(f"ML-DSA Public Key: {IdentityManager._PQC_PUBLIC_KEY_PATH}")
        print(f"ML-KEM Public Key: {IdentityManager._PQC_KEM_PUBLIC_KEY_PATH}")
        print(
            "\n[Action Required] Copy the PQC Public Key to your remote "
            "servers if using Strict Zero Trust."
        )

    elif args.command == "manifest":
        print("🛡️  Generating Integrity Manifest...")
        # Path to project root
        root_path = Path(__file__).resolve().parent.parent.parent
        verifier = IntegrityVerifier(root_path)
        if verifier.rebuild_manifest():
            print(f"✅ Integrity manifest signed and saved to {verifier.MANIFEST_PATH}")
        else:
            print("❌ Failed to generate manifest.")
            sys.exit(1)

    elif args.command == "decrypt-log":
        from llm_cli.apps.pqc_decrypt import decrypt_log_file

        print(f"🛡️  Decrypting log file: {args.input}...")
        decrypt_log_file(Path(args.input), Path(args.output) if args.output else None)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
