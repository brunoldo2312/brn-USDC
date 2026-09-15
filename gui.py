"""Interface Tkinter do nó BRN."""
from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from blockchain import (apply_block, build_next_block,
                        check_blockchain_validity, make_transaction,
                        validate_transaction)
from carteira import encrypt_private_key, generate_keypair
from db import BlockchainDB
from p2p_rede import AutoNodeDiscovery


class BRNNodeApp:
    def __init__(self, root: tk.Tk, db_path: str = "brn_node.db",
                 p2p_port: int = 7777):
        self.root = root
        self.root.title("BRN Node")
        self.root.geometry("900x620")

        self.db = BlockchainDB(db_path)
        self.p2p_port = p2p_port
        self.discovery = AutoNodeDiscovery(
            p2p_port=p2p_port,
            gui_callback=self.log,
            on_peer=self._on_peer,
        )
        self.mining_stop = threading.Event()
        self.current_password = ""

        self._build_ui()
        self._ensure_genesis()
        self._refresh_stats()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)

        self.tab_wallet = ttk.Frame(nb)
        self.tab_mine = ttk.Frame(nb)
        self.tab_p2p = ttk.Frame(nb)
        self.tab_explorer = ttk.Frame(nb)

        nb.add(self.tab_wallet, text="Carteira")
        nb.add(self.tab_mine, text="Mineração")
        nb.add(self.tab_p2p, text="P2P")
        nb.add(self.tab_explorer, text="Explorer")

        self._build_wallet()
        self._build_mine()
        self._build_p2p()
        self._build_explorer()

    # ---------------- Aba: Carteira ----------------
    def _build_wallet(self) -> None:
        f = self.tab_wallet
        ttk.Label(f, text="Senha:").grid(
            row=0, column=0, padx=6, pady=6, sticky="e")
        self.ent_pwd = ttk.Entry(f, show="*", width=40)
        self.ent_pwd.grid(row=0, column=1, padx=6, pady=6, sticky="w")

        ttk.Button(f, text="Criar nova carteira",
                   command=self.create_wallet).grid(
            row=1, column=0, padx=6, pady=6)
        ttk.Button(f, text="Recarregar lista",
                   command=self.refresh_wallets).grid(
            row=1, column=1, padx=6, pady=6, sticky="w")

        cols = ("address", "balance", "usdc")
        self.tree_wallet = ttk.Treeview(f, columns=cols, show="headings",
                                        height=8)
        self.tree_wallet.heading("address", text="Endereço")
        self.tree_wallet.heading("balance", text="Saldo BRN")
        self.tree_wallet.heading("usdc", text="Endereço USDC")
        self.tree_wallet.column("address", width=320)
        self.tree_wallet.column("balance", width=120, anchor="e")
        self.tree_wallet.column("usdc", width=280)
        self.tree_wallet.grid(row=2, column=0, columnspan=2,
                              padx=6, pady=6, sticky="nsew")

        ttk.Label(f, text="Enviar BRN").grid(
            row=3, column=0, columnspan=2, pady=(12, 2), sticky="w")
        frame_tx = ttk.Frame(f)
        frame_tx.grid(row=4, column=0, columnspan=2, padx=6, sticky="ew")

        ttk.Label(frame_tx, text="De:").grid(row=0, column=0, sticky="e")
        self.ent_from = ttk.Entry(frame_tx, width=42)
        self.ent_from.grid(row=0, column=1, padx=4, pady=2, sticky="w")

        ttk.Label(frame_tx, text="Para:").grid(row=1, column=0, sticky="e")
        self.ent_to = ttk.Entry(frame_tx, width=42)
        self.ent_to.grid(row=1, column=1, padx=4, pady=2, sticky="w")

        ttk.Label(frame_tx, text="Valor:").grid(row=2, column=0, sticky="e")
        self.ent_amount = ttk.Entry(frame_tx, width=20)
        self.ent_amount.grid(row=2, column=1, padx=4, pady=2, sticky="w")

        ttk.Button(frame_tx, text="Assinar e enviar",
                   command=self.send_tx).grid(
            row=3, column=1, padx=4, pady=6, sticky="w")

        f.rowconfigure(2, weight=1)
        f.columnconfigure(1, weight=1)

    # ---------------- Aba: Mineração ----------------
    def _build_mine(self) -> None:
        f = self.tab_mine
        ttk.Label(f, text="Endereço do minerador:").grid(
            row=0, column=0, padx=6, pady=6, sticky="e")
        self.ent_miner = ttk.Entry(f, width=48)
        self.ent_miner.grid(row=0, column=1, padx=6, pady=6, sticky="w")

        self.btn_mine = ttk.Button(f, text="Minerar 1 bloco",
                                   command=self.mine_one)
        self.btn_mine.grid(row=1, column=0, padx=6, pady=6)

        self.btn_auto = ttk.Button(f, text="Minerar contínuo",
                                   command=self.mine_loop)
        self.btn_auto.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        self.btn_stop = ttk.Button(f, text="Parar",
                                   command=self.stop_mining)
        self.btn_stop.grid(row=1, column=2, padx=6, pady=6, sticky="w")

        ttk.Label(f, text="Status:").grid(
            row=2, column=0, padx=6, pady=6, sticky="ne")
        self.txt_mine = scrolledtext.ScrolledText(f, height=18, width=90)
        self.txt_mine.grid(row=2, column=1, columnspan=3,
                           padx=6, pady=6, sticky="nsew")
        f.rowconfigure(2, weight=1)
        f.columnconfigure(1, weight=1)

    # ---------------- Aba: P2P ----------------
    def _build_p2p(self) -> None:
        f = self.tab_p2p
        self.lbl_p2p = ttk.Label(f, text="Descoberta: parada")
        self.lbl_p2p.grid(row=0, column=0, columnspan=3,
                          padx=6, pady=6, sticky="w")

        ttk.Button(f, text="Iniciar descoberta",
                   command=self.start_p2p).grid(
            row=1, column=0, padx=6, pady=6)
        ttk.Button(f, text="Parar",
                   command=self.stop_p2p).grid(
            row=1, column=1, padx=6, pady=6)
        ttk.Button(f, text="Atualizar lista",
                   command=self.refresh_peers).grid(
            row=1, column=2, padx=6, pady=6)

        self.lst_peers = tk.Listbox(f, height=18)
        self.lst_peers.grid(row=2, column=0, columnspan=3,
                            padx=6, pady=6, sticky="nsew")
        f.rowconfigure(2, weight=1)
        f.columnconfigure(0, weight=1)

    # ---------------- Aba: Explorer ----------------
    def _build_explorer(self) -> None:
        f = self.tab_explorer
        self.lbl_stats = ttk.Label(f, text="")
        self.lbl_stats.grid(row=0, column=0, columnspan=3,
                            padx=6, pady=6, sticky="w")

        ttk.Button(f, text="Atualizar",
                   command=self.refresh_explorer).grid(
            row=1, column=0, padx=6, pady=6, sticky="w")

        cols = ("height", "hash", "prev", "ts", "diff", "nonce", "txs")
        self.tree_blocks = ttk.Treeview(f, columns=cols, show="headings")
        for c, t, w in (
            ("height", "#", 50),
            ("hash", "Hash", 200),
            ("prev", "Anterior", 200),
            ("ts", "Timestamp", 140),
            ("diff", "Dif.", 50),
            ("nonce", "Nonce", 80),
            ("txs", "TXs", 50),
        ):
            self.tree_blocks.heading(c, text=t)
            self.tree_blocks.column(c, width=w)
        self.tree_blocks.grid(row=2, column=0, columnspan=3,
                              padx=6, pady=6, sticky="nsew")
        f.rowconfigure(2, weight=1)
        f.columnconfigure(0, weight=1)

        ttk.Label(f, text="Log:").grid(
            row=3, column=0, padx=6, pady=(6, 0), sticky="w")
        self.txt_log = scrolledtext.ScrolledText(f, height=8, width=100)
        self.txt_log.grid(row=4, column=0, columnspan=3,
                          padx=6, pady=6, sticky="nsew")

    # ---------------- utilidades ----------------
    def log(self, msg: str) -> None:
        """Escreve no log do Explorer e no stdout."""
        try:
            self.txt_log.insert("end", msg + "\n")
            self.txt_log.see("end")
        except Exception:
            pass
        print(msg)

    # ---------------- carteira ----------------
    def create_wallet(self) -> None:
        pwd = self.ent_pwd.get()
        if len(pwd) < 6:
            messagebox.showwarning("Senha curta",
                                   "Use pelo menos 6 caracteres.")
            return
        priv_hex, address = generate_keypair()
        try:
            ct, salt = encrypt_private_key(priv_hex, pwd)
        except RuntimeError as e:
            messagebox.showerror("Erro", str(e))
            return
        self.db.wallet_save(address, ct, salt, balance=0.0)
        self.current_password = pwd
        self.log(f"Carteira criada: {address}")
        self.refresh_wallets()
        self.ent_miner.delete(0, "end")
        self.ent_miner.insert(0, address)
        self.ent_from.delete(0, "end")
        self.ent_from.insert(0, address)

    def refresh_wallets(self) -> None:
        for i in self.tree_wallet.get_children():
            self.tree_wallet.delete(i)
        for w in self.db.wallet_list():
            self.tree_wallet.insert(
                "", "end",
                values=(w["address"], f"{w['balance']:.8f}",
                        w.get("usdc_address", "") or "—"),
            )

    # ---------------- transações ----------------
    def send_tx(self) -> None:
        sender = self.ent_from.get().strip()
        recipient = self.ent_to.get().strip()
        try:
            amount = float(self.ent_amount.get())
        except ValueError:
            messagebox.showwarning("Valor inválido",
                                   "Digite um número.")
            return

        w = self.db.wallet_get(sender)
        if w is None:
            messagebox.showerror("Erro", "Remetente desconhecido.")
            return
        if self.db.wallet_get(recipient) is None:
            messagebox.showerror("Erro", "Destinatário desconhecido.")
            return

        tx = make_transaction(sender, recipient, amount)
        ok, why = validate_transaction(tx, self.db)
        if not ok:
            messagebox.showerror("Transação rejeitada", why)
            return

        self.db.mempool_add(tx["txid"], json.dumps(tx))
        self.log(f"TX na mempool: {tx['txid'][:16]}… "
                 f"({amount} BRN → {recipient[:12]}…)")
    # ---------------- mineração ----------------
    def _ensure_genesis(self) -> None:
        if self.db.height >= 0:
            return
        wallets = self.db.wallet_list()
        if wallets:
            miner = wallets[0]["address"]
        else:
            priv, miner = generate_keypair()
            self.db.wallet_save(miner, "x", "y", balance=0.0)
        blk = build_next_block(self.db, miner)
        blk.mine()
        apply_block(self.db, blk)
        self.log(f"Genesis minerado: {blk.hash[:16]}…")

    def mine_one(self) -> None:
        miner = self.ent_miner.get().strip()
        if not miner:
            messagebox.showwarning("Sem endereço",
                                   "Informe o endereço do minerador.")
            return
        if self.db.wallet_get(miner) is None:
            self.db.wallet_save(miner, "x", "y", balance=0.0)

        def worker():
            try:
                blk = build_next_block(self.db, miner)
                self.log(f"Minerando bloco #{blk.index} "
                         f"(diff={blk.difficulty})…")
                blk.mine(status_callback=self.log,
                         stop_event=self.mining_stop)
                apply_block(self.db, blk)
                self.log(f"Bloco aceito: {blk.hash[:16]}…")
                self.root.after(0, self._refresh_stats)
                self.root.after(0, self.refresh_wallets)
                self.root.after(0, self.refresh_explorer)
            except RuntimeError as e:
                self.log(f"Mineração interrompida: {e}")
            except Exception as e:
                self.log(f"Erro na mineração: {e}")

        self.mining_stop.clear()
        threading.Thread(target=worker, daemon=True).start()

    def mine_loop(self) -> None:
        def worker():
            while not self.mining_stop.is_set():
                miner = self.ent_miner.get().strip()
                if not miner:
                    break
                try:
                    blk = build_next_block(self.db, miner)
                    blk.mine(status_callback=self.log,
                             stop_event=self.mining_stop)
                    apply_block(self.db, blk)
                    self.log(f"Bloco #{blk.index} minerado "
                             f"{blk.hash[:16]}…")
                    self.root.after(0, self._refresh_stats)
                    self.root.after(0, self.refresh_wallets)
                    self.root.after(0, self.refresh_explorer)
                except RuntimeError:
                    break
                except Exception as e:
                    self.log(f"Erro: {e}")
                    break
            self.log("Mineração contínua parada.")

        self.mining_stop.clear()
        threading.Thread(target=worker, daemon=True).start()

    def stop_mining(self) -> None:
        self.mining_stop.set()
        self.log("Parada solicitada.")

    # ---------------- P2P ----------------
    def _on_peer(self, ip: str, port: int) -> None:
        self.root.after(0, self.refresh_peers)

    def start_p2p(self) -> None:
        self.discovery.start()
        self.lbl_p2p.config(
            text=f"Descoberta: ativa em "
                 f"{self.discovery.local_ip}:{self.p2p_port}"
        )

    def stop_p2p(self) -> None:
        self.discovery.stop()
        self.lbl_p2p.config(text="Descoberta: parada")

    def refresh_peers(self) -> None:
        self.lst_peers.delete(0, "end")
        for p in self.discovery.get_peers():
            self.lst_peers.insert("end", p)

    # ---------------- explorer ----------------
    def _refresh_stats(self) -> None:
        h = self.db.height
        tip = self.db.tip_hash[:16]
        mp = self.db.mempool_size()
        valid = check_blockchain_validity(self.db)
        self.lbl_stats.config(
            text=f"Altura: {h}   |   Tip: {tip}…   |   "
                 f"Mempool: {mp}   |   "
                 f"Cadeia válida: {'SIM' if valid else 'NÃO'}"
        )

    def refresh_explorer(self) -> None:
        self._refresh_stats()
        for i in self.tree_blocks.get_children():
            self.tree_blocks.delete(i)
        chain = self.db.get_raw_chain()
        for b in reversed(chain[-50:]):
            self.tree_blocks.insert(
                "", "end",
                values=(
                    b["index"],
                    b["hash"][:24] + "…",
                    b["previous_hash"][:24] + "…",
                    f"{b['timestamp']:.0f}",
                    b["difficulty"],
                    b["nonce"],
                    len(b["transactions"]),
                ),
            )

    # ---------------- encerramento ----------------
    def on_close(self) -> None:
        try:
            self.mining_stop.set()
            self.discovery.stop()
            self.db.close()
        finally:
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    BRNNodeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()