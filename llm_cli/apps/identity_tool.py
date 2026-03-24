import argparse
import logging
import sys
from pathlib import Path

from llm_cli.security.identity import IdentityManager
from llm_cli.security.integrity import IntegrityVerifier
from llm_cli.security.permissions import setup_permissions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    # Enforce strict user-only permissions and set umask
    setup_permissions()

    parser = argparse.ArgumentParser(
        description="LLM-CLI Identity and Integrity Management Tool"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # keygen command
    subparsers.add_parser("keygen", help="Generate RSA and PQC key pairs")

    # manifest command
    subparsers.add_parser("manifest", help="Generate/Update integrity manifest")

    # verify-session command
    verify_parser = subparsers.add_parser(
        "verify-session", help="Verify session integrity using Merkle Anchor"
    )
    verify_parser.add_argument("trace_id", help="Session Trace ID to verify")

    # list-anchors command
    subparsers.add_parser("list-anchors", help="List available session anchors")

    # decrypt-log command
    decrypt_parser = subparsers.add_parser(
        "decrypt-log", help="Decrypt PQC-encrypted (ML-KEM) audit logs"
    )
    decrypt_parser.add_argument(
        "input", help="Path to the encrypted audit log (.jsonl)"
    )
    decrypt_parser.add_argument("-o", "--output", help="Path to save the decrypted log")

    # verify command (full PQC audit-log verification)
    verify_full_parser = subparsers.add_parser(
        "verify",
        help=(
            "Full integrity verification (all lines PQC-verified). "
            "Slower than the startup check but exhaustive."
        ),
    )
    verify_full_parser.add_argument(
        "--tail",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Verify only the last N lines with PQC (0 = all lines, default: 0). "
            "Hash-chain is always verified for all lines."
        ),
    )

    try:
        args = parser.parse_args()

        if args.command == "keygen":
            print("🛡️  Generating Identity Keys...")
            IdentityManager._ensure_keys(force=True)
            print(f"✅ Keys generated in {IdentityManager._KEY_DIR}")
            pub_key = IdentityManager._PRIVATE_KEY_PATH.with_suffix(".pub")
            print(f"RSA Public Key: {pub_key}")
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
                msg = f"✅ Integrity manifest saved to {verifier.MANIFEST_PATH}"
                print(msg)
            else:
                print("❌ Failed to generate manifest.")
                sys.exit(1)

        elif args.command == "verify-session":
            from llm_cli.security.merkle_anchor import SessionAnchorManager

            print(f"🛡️  Verifying session: {args.trace_id}...")
            if SessionAnchorManager.verify_session(args.trace_id):
                print(
                    f"✅ Session {args.trace_id} integrity verified "
                    "via PQC-signed Merkle Anchor."
                )
            else:
                print(f"❌ Session {args.trace_id} integrity check failed.")
                sys.exit(1)

        elif args.command == "list-anchors":
            import json

            from llm_cli.security.merkle_anchor import ANCHOR_DIR

            if not ANCHOR_DIR.exists():
                print("No session anchors found.")
                return

            print("🛡️  Available Session Anchors:")
            for anchor_file in ANCHOR_DIR.glob("*.anchor.json"):
                try:
                    with anchor_file.open("r", encoding="utf-8") as f:
                        anchor = json.load(f)
                        tid = anchor.get("trace_id", "Unknown")
                        ts = anchor.get("timestamp", "Unknown")
                        count = anchor.get("entry_count", 0)
                        print(f"  - Trace ID: {tid} | Time: {ts} | Logs: {count}")
                except Exception:
                    continue

        elif args.command == "decrypt-log":
            from llm_cli.apps.pqc_decrypt import decrypt_log_file

            print(f"🛡️  Decrypting log file: {args.input}...")
            decrypt_log_file(
                Path(args.input), Path(args.output) if args.output else None
            )

        elif args.command == "verify":
            root_path = Path(__file__).resolve().parent.parent.parent
            verifier = IntegrityVerifier(root_path)

            # pqc_verify_tail_lines=0 means verify ALL lines (no tail restriction)
            tail = args.tail if args.tail > 0 else 10**9
            label = "all" if args.tail == 0 else f"last {args.tail}"
            print(
                f"🛡️  Running full integrity check (PQC verify on {label} audit lines)…"
            )

            ok = verifier.verify(pqc_verify_tail_lines=tail)
            if ok:
                print("✅ Integrity check passed.")
            else:
                print("❌ Integrity check failed. See log output above for details.")
                sys.exit(1)
        else:
            parser.print_help()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
