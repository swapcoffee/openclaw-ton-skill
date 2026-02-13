#!/usr/bin/env python3
"""
OpenClaw TON Skill — Мониторинг транзакций

Real-time мониторинг кошельков через TonAPI SSE или polling fallback.

CLI:
  monitor.py start -p <password>         — запуск (foreground)
  monitor.py start -p <password> --daemon — запуск в фоне
  monitor.py status                       — статус мониторинга
  monitor.py stop                         — остановка
"""

import os
import sys
import json
import signal
import time
import argparse
import getpass
import threading
import logging
from pathlib import Path
from datetime import datetime, UTC
from typing import Optional, List, Dict, Any

# Локальный импорт
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from utils import (  # noqa: E402
    load_config,
    ensure_skill_dir,
    tonapi_request,
    normalize_address,
    raw_to_friendly,
    SKILL_DIR,
    TONAPI_BASE,
)

from wallet import WalletStorage  # noqa: E402

# Зависимости
try:
    import requests
except ImportError:
    print(json.dumps({"error": "Missing dependency: requests"}))
    sys.exit(1)
    raise SystemExit

try:
    import sseclient

    SSE_AVAILABLE = True
except ImportError:
    SSE_AVAILABLE = False


# =============================================================================
# Константы
# =============================================================================

MONITOR_STATE_FILE = SKILL_DIR / "monitor_state.json"
MONITOR_LOG_FILE = SKILL_DIR / "monitor.log"
MONITOR_PID_FILE = SKILL_DIR / "monitor.pid"

# Polling интервал (fallback)
POLL_INTERVAL = 30  # секунд

# SSE reconnect delay
SSE_RECONNECT_DELAY = 5  # секунд


# =============================================================================
# Logging
# =============================================================================


def setup_logging(log_file: Path, verbose: bool = False) -> logging.Logger:
    """Настройка логирования в файл и stderr."""
    ensure_skill_dir()

    logger = logging.getLogger("ton-monitor")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Формат
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Stderr handler (для daemon)
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    return logger


# =============================================================================
# State Management
# =============================================================================


def load_state() -> Dict[str, Any]:
    """Загружает состояние мониторинга."""
    ensure_skill_dir()
    if MONITOR_STATE_FILE.exists():
        try:
            with open(MONITOR_STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_seen": {}, "started_at": None}


def save_state(state: Dict[str, Any]) -> None:
    """Сохраняет состояние мониторинга."""
    ensure_skill_dir()
    with open(MONITOR_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def update_last_seen(address: str, event_id: str) -> None:
    """Обновляет last_seen для адреса."""
    state = load_state()
    state["last_seen"][address] = {
        "event_id": event_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    save_state(state)


def get_last_seen(address: str) -> Optional[str]:
    """Возвращает last_seen event_id для адреса."""
    state = load_state()
    return state.get("last_seen", {}).get(address, {}).get("event_id")


# =============================================================================
# Event Processing
# =============================================================================


def parse_transaction(
    tx: dict, wallet_label: str, wallet_address: str
) -> Optional[dict]:
    """
    Парсит транзакцию и возвращает событие в нужном формате.

    TonAPI возвращает разные форматы для SSE и events endpoint.
    """
    try:
        # Определяем тип транзакции
        actions = tx.get("actions", [])

        event = {
            "wallet": wallet_label,
            "address": wallet_address,
            "timestamp": datetime.now(UTC).isoformat(),
            "tx_hash": tx.get("event_id") or tx.get("hash") or tx.get("lt"),
            "raw": tx,  # для отладки
        }

        # Парсим actions
        if not actions:
            # Простая транзакция без actions
            event["type"] = "other"
            event["description"] = "Unknown transaction"
            return event

        # Берём первый action (основной)
        action = actions[0]
        action_type = action.get("type", "Unknown")

        # Нормализуем наш адрес для сравнения
        try:
            our_raw = normalize_address(wallet_address, "raw")
        except Exception:
            our_raw = wallet_address.lower()

        if action_type == "TonTransfer":
            ton_transfer = action.get("TonTransfer", {})
            sender = ton_transfer.get("sender", {}).get("address", "")
            recipient = ton_transfer.get("recipient", {}).get("address", "")
            amount = int(ton_transfer.get("amount", 0)) / 1e9

            # Определяем направление
            try:
                sender_raw = normalize_address(sender, "raw") if sender else ""
            except Exception:
                sender_raw = sender.lower() if sender else ""

            if sender_raw == our_raw:
                event["type"] = "outgoing_transfer"
                event["to"] = recipient
                event["amount"] = f"{amount:.4f} TON"
            else:
                event["type"] = "incoming_transfer"
                event["from"] = sender
                event["amount"] = f"{amount:.4f} TON"

        elif action_type == "JettonTransfer":
            jetton = action.get("JettonTransfer", {})
            sender = jetton.get("sender", {}).get("address", "")
            recipient = jetton.get("recipient", {}).get("address", "")
            amount = jetton.get("amount", "0")
            jetton_info = jetton.get("jetton", {})
            symbol = jetton_info.get("symbol", "???")
            decimals = jetton_info.get("decimals", 9)

            human_amount = float(amount) / (10**decimals)

            try:
                sender_raw = normalize_address(sender, "raw") if sender else ""
            except Exception:
                sender_raw = sender.lower() if sender else ""

            if sender_raw == our_raw:
                event["type"] = "outgoing_transfer"
                event["to"] = recipient
            else:
                event["type"] = "incoming_transfer"
                event["from"] = sender

            event["amount"] = f"{human_amount:.4f} {symbol}"
            event["token"] = symbol

        elif action_type == "JettonSwap":
            swap = action.get("JettonSwap", {})
            dex = swap.get("dex", "Unknown DEX")

            # Что отдали
            amount_in = swap.get("amount_in", "0")
            jetton_in = swap.get("jetton_master_in", {})
            symbol_in = jetton_in.get("symbol", "TON")
            decimals_in = jetton_in.get("decimals", 9)

            # Что получили
            amount_out = swap.get("amount_out", "0")
            jetton_out = swap.get("jetton_master_out", {})
            symbol_out = jetton_out.get("symbol", "TON")
            decimals_out = jetton_out.get("decimals", 9)

            human_in = float(amount_in) / (10**decimals_in) if amount_in else 0
            human_out = float(amount_out) / (10**decimals_out) if amount_out else 0

            event["type"] = "swap"
            event["dex"] = dex
            event["amount"] = (
                f"{human_in:.4f} {symbol_in} → {human_out:.4f} {symbol_out}"
            )

        elif action_type == "NftItemTransfer":
            nft = action.get("NftItemTransfer", {})
            sender = nft.get("sender", {}).get("address", "")
            recipient = nft.get("recipient", {}).get("address", "")
            nft_item = nft.get("nft", "")

            event["type"] = "nft_transfer"

            try:
                sender_raw = normalize_address(sender, "raw") if sender else ""
            except Exception:
                sender_raw = sender.lower() if sender else ""

            if sender_raw == our_raw:
                event["to"] = recipient
                event["direction"] = "outgoing"
            else:
                event["from"] = sender
                event["direction"] = "incoming"

            event["nft"] = nft_item
            event["amount"] = "1 NFT"

        else:
            event["type"] = "other"
            event["action_type"] = action_type
            event["description"] = action.get("simple_preview", {}).get(
                "description", action_type
            )

        # Убираем raw из финального вывода
        del event["raw"]

        return event

    except Exception as e:
        return {
            "type": "error",
            "wallet": wallet_label,
            "address": wallet_address,
            "error": str(e),
            "timestamp": datetime.now(UTC).isoformat(),
        }


def emit_event(event: dict, logger: logging.Logger) -> None:
    """Выводит событие в stdout (JSON) и логирует."""
    json_str = json.dumps(event, ensure_ascii=False)

    # stdout для парсинга агентом
    print(json_str, flush=True)

    # Лог
    logger.info(
        f"Event: {event.get('type')} | {event.get('wallet')} | {event.get('amount', 'N/A')}"
    )


# =============================================================================
# SSE Monitor (Вариант 1 - предпочтительный)
# =============================================================================


class SSEMonitor:
    """Real-time мониторинг через TonAPI SSE."""

    def __init__(
        self,
        addresses: List[str],
        wallet_map: Dict[str, str],  # address -> label
        logger: logging.Logger,
        api_key: Optional[str] = None,
    ):
        self.addresses = addresses
        self.wallet_map = wallet_map
        self.logger = logger
        self.api_key = api_key
        self.running = False
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Запускает SSE мониторинг."""
        if not SSE_AVAILABLE:
            raise RuntimeError(
                "sseclient not available. Install: pip install sseclient-py"
            )

        self.running = True
        self._stop_event.clear()

        while self.running and not self._stop_event.is_set():
            try:
                self._connect_and_listen()
            except Exception as e:
                self.logger.error(f"SSE error: {e}")
                if self.running:
                    self.logger.info(f"Reconnecting in {SSE_RECONNECT_DELAY}s...")
                    time.sleep(SSE_RECONNECT_DELAY)

    def stop(self) -> None:
        """Останавливает мониторинг."""
        self.running = False
        self._stop_event.set()

    def _connect_and_listen(self) -> None:
        """Подключается к SSE и слушает события."""
        accounts = ",".join(self.addresses)
        url = f"{TONAPI_BASE}/sse/accounts/transactions?accounts={accounts}"

        headers = {"Accept": "text/event-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.logger.info(f"Connecting to SSE: {len(self.addresses)} addresses")

        response = requests.get(url, headers=headers, stream=True, timeout=None)
        response.raise_for_status()

        client = sseclient.SSEClient(response)

        self.logger.info("SSE connected, listening for events...")

        for event in client:
            if not self.running or self._stop_event.is_set():
                break

            if event.event == "message" and event.data:
                try:
                    tx = json.loads(event.data)
                    self._process_sse_event(tx)
                except json.JSONDecodeError:
                    self.logger.warning(
                        f"Invalid JSON in SSE event: {event.data[:100]}"
                    )

    def _process_sse_event(self, tx: dict) -> None:
        """Обрабатывает SSE событие."""
        # SSE событие содержит account_id в поле account
        account_id = tx.get("account_id", "")

        # Ищем label для этого адреса
        wallet_label = None
        wallet_address = None

        for addr, label in self.wallet_map.items():
            try:
                addr_raw = normalize_address(addr, "raw")
                if addr_raw == account_id or addr == account_id:
                    wallet_label = label
                    wallet_address = addr
                    break
            except Exception:
                if addr.lower() == account_id.lower():
                    wallet_label = label
                    wallet_address = addr
                    break

        if not wallet_label or not wallet_address:
            # Используем адрес как есть
            wallet_label = account_id[:16] + "..."
            wallet_address = account_id

        # Парсим и эмитим событие
        event = parse_transaction(tx, wallet_label, wallet_address)
        if event:
            emit_event(event, self.logger)

            # Обновляем last_seen
            event_id = tx.get("event_id") or tx.get("lt")
            if event_id:
                update_last_seen(wallet_address, str(event_id))


# =============================================================================
# Polling Monitor (Вариант 2 - fallback)
# =============================================================================


class PollingMonitor:
    """Polling мониторинг через TonAPI events endpoint."""

    def __init__(
        self,
        addresses: List[str],
        wallet_map: Dict[str, str],
        logger: logging.Logger,
        interval: int = POLL_INTERVAL,
    ):
        self.addresses = addresses
        self.wallet_map = wallet_map
        self.logger = logger
        self.interval = interval
        self.running = False
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Запускает polling мониторинг."""
        self.running = True
        self._stop_event.clear()

        self.logger.info(
            f"Starting polling monitor: {len(self.addresses)} addresses, {self.interval}s interval"
        )

        while self.running and not self._stop_event.is_set():
            for address in self.addresses:
                if not self.running:
                    break

                try:
                    self._check_address(address)
                except Exception as e:
                    self.logger.error(f"Error checking {address}: {e}")

            # Ждём интервал
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        """Останавливает мониторинг."""
        self.running = False
        self._stop_event.set()

    def _check_address(self, address: str) -> None:
        """Проверяет новые события для адреса."""
        label = self.wallet_map.get(address, address[:16] + "...")

        # Получаем события
        try:
            friendly = raw_to_friendly(address) if ":" in address else address
        except Exception:
            friendly = address

        result = tonapi_request(f"/accounts/{friendly}/events", params={"limit": 10})

        if not result["success"]:
            self.logger.warning(
                f"Failed to get events for {label}: {result.get('error')}"
            )
            return

        events = result["data"].get("events", [])
        if not events:
            return

        # Получаем last_seen
        last_seen = get_last_seen(address)

        # Обрабатываем новые события (в обратном порядке, старые первыми)
        new_events = []
        for ev in reversed(events):
            event_id = ev.get("event_id", "")

            if last_seen and event_id == last_seen:
                break

            new_events.append(ev)

        # Эмитим события
        for ev in new_events:
            event = parse_transaction(ev, label, address)
            if event:
                emit_event(event, self.logger)

        # Обновляем last_seen
        if events:
            latest_id = events[0].get("event_id", "")
            if latest_id:
                update_last_seen(address, latest_id)


# =============================================================================
# Main Monitor
# =============================================================================


class TONMonitor:
    """Главный класс мониторинга."""

    def __init__(
        self,
        password: str,
        wallets: Optional[List[str]] = None,
        use_sse: bool = True,
        verbose: bool = False,
    ):
        self.password = password
        self.wallet_filter = wallets
        self.use_sse = use_sse and SSE_AVAILABLE
        self.verbose = verbose

        self.logger = setup_logging(MONITOR_LOG_FILE, verbose)
        self.monitor = None
        self._running = False

    def start(self) -> None:
        """Запускает мониторинг."""
        # Загружаем кошельки
        storage = WalletStorage(self.password)
        all_wallets = storage.get_wallets(include_secrets=False)

        if not all_wallets:
            self.logger.error("No wallets found")
            print(json.dumps({"error": "No wallets configured"}))
            return sys.exit(1)

        # Фильтруем если указаны конкретные
        if self.wallet_filter:
            wallets = []
            for w in all_wallets:
                if (
                    w.get("label") in self.wallet_filter
                    or w.get("address") in self.wallet_filter
                ):
                    wallets.append(w)
        else:
            wallets = all_wallets

        if not wallets:
            self.logger.error(f"No wallets matching filter: {self.wallet_filter}")
            print(
                json.dumps(
                    {"error": f"No wallets matching filter: {self.wallet_filter}"}
                )
            )
            return sys.exit(1)

        # Строим карту адрес -> label
        addresses = []
        wallet_map = {}

        for w in wallets:
            addr = w.get("address", "")
            label = w.get("label", "")
            addresses.append(addr)
            wallet_map[addr] = label

        # Конфиг
        config = load_config()
        api_key = config.get("tonapi_key", "")

        self.logger.info(f"Starting monitor: {len(addresses)} wallets")
        self.logger.info(f"Mode: {'SSE (real-time)' if self.use_sse else 'Polling'}")

        # Сохраняем PID
        self._save_pid()

        # Обновляем state
        state = load_state()
        state["started_at"] = datetime.now(UTC).isoformat()
        state["wallets"] = [w.get("label") for w in wallets]
        state["mode"] = "sse" if self.use_sse else "polling"
        save_state(state)

        # Обработка сигналов
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        # Запускаем
        self._running = True

        try:
            if self.use_sse:
                self.monitor = SSEMonitor(addresses, wallet_map, self.logger, api_key)
            else:
                self.monitor = PollingMonitor(addresses, wallet_map, self.logger)

            self.monitor.start()
        finally:
            self._cleanup()

    def _signal_handler(self, signum, frame):
        """Обработчик сигналов."""
        self.logger.info(f"Received signal {signum}, stopping...")
        self.stop()

    def stop(self) -> None:
        """Останавливает мониторинг."""
        self._running = False
        if self.monitor:
            self.monitor.stop()

    def _save_pid(self) -> None:
        """Сохраняет PID процесса."""
        ensure_skill_dir()
        with open(MONITOR_PID_FILE, "w") as f:
            f.write(str(os.getpid()))

    def _cleanup(self) -> None:
        """Очистка при завершении."""
        try:
            MONITOR_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

        state = load_state()
        state["started_at"] = None
        save_state(state)

        self.logger.info("Monitor stopped")


# =============================================================================
# CLI Commands
# =============================================================================


def cmd_start(args) -> None:
    """Запуск мониторинга."""
    # Получаем пароль
    password = args.password or os.environ.get("WALLET_PASSWORD")

    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass("Wallet password: ")
        else:
            print(
                json.dumps(
                    {"error": "Password required. Use -p or WALLET_PASSWORD env"}
                )
            )
            return sys.exit(1)

    # Daemon mode
    if args.daemon:
        # Fork
        pid = os.fork()
        if pid > 0:
            # Parent
            print(
                json.dumps(
                    {
                        "success": True,
                        "action": "started",
                        "pid": pid,
                        "mode": "daemon",
                        "log": str(MONITOR_LOG_FILE),
                    }
                )
            )
            sys.exit(0)
        else:
            # Child - detach
            os.setsid()

            # Redirect stdout/stderr
            sys.stdout = open(MONITOR_LOG_FILE, "a")
            sys.stderr = sys.stdout

    # Запускаем
    wallets = args.wallet if args.wallet else None
    use_sse = not args.polling

    monitor = TONMonitor(
        password=password, wallets=wallets, use_sse=use_sse, verbose=args.verbose
    )

    monitor.start()


def cmd_status(args) -> None:
    """Статус мониторинга."""
    state = load_state()

    result = {
        "running": False,
        "started_at": state.get("started_at"),
        "wallets": state.get("wallets", []),
        "mode": state.get("mode", "unknown"),
        "last_seen": state.get("last_seen", {}),
    }

    # Проверяем PID
    if MONITOR_PID_FILE.exists():
        try:
            with open(MONITOR_PID_FILE, "r") as f:
                pid = int(f.read().strip())

            # Проверяем жив ли процесс
            os.kill(pid, 0)
            result["running"] = True
            result["pid"] = pid
        except (ValueError, OSError):
            # Процесс умер
            MONITOR_PID_FILE.unlink(missing_ok=True)

    print(json.dumps(result, indent=2))


def cmd_stop(args) -> None:
    """Остановка мониторинга."""
    if not MONITOR_PID_FILE.exists():
        print(json.dumps({"success": False, "error": "Monitor not running"}))
        return sys.exit(1)

    try:
        with open(MONITOR_PID_FILE, "r") as f:
            pid = int(f.read().strip())

        os.kill(pid, signal.SIGTERM)

        # Ждём завершения
        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except OSError:
                break

        MONITOR_PID_FILE.unlink(missing_ok=True)

        print(json.dumps({"success": True, "action": "stopped", "pid": pid}))

    except ValueError:
        print(json.dumps({"success": False, "error": "Invalid PID file"}))
        return sys.exit(1)
    except OSError as e:
        print(json.dumps({"success": False, "error": str(e)}))
        return sys.exit(1)


# =============================================================================
# Main
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="TON Transaction Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s start -p password           # Foreground
  %(prog)s start -p password --daemon  # Background
  %(prog)s start -p password --wallet trading --wallet main
  %(prog)s status
  %(prog)s stop
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- start ---
    start_p = subparsers.add_parser("start", help="Start monitoring")
    start_p.add_argument("--password", "-p", help="Wallet encryption password")
    start_p.add_argument(
        "--wallet", "-w", action="append", help="Specific wallet(s) to monitor"
    )
    start_p.add_argument("--daemon", "-d", action="store_true", help="Run as daemon")
    start_p.add_argument(
        "--polling", action="store_true", help="Use polling instead of SSE"
    )
    start_p.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    # --- status ---
    subparsers.add_parser("status", help="Show monitor status")

    # --- stop ---
    subparsers.add_parser("stop", help="Stop monitoring")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return sys.exit(1)

    commands = {
        "start": cmd_start,
        "status": cmd_status,
        "stop": cmd_stop,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
