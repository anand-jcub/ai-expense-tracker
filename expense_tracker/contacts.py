""""
contacts.py — Contact Ledger logic.

Tracks who owes you money (and who you owe) across informal
transactions: loans, rolling money, food splits, etc.

Key concepts:
  - Contact: a person you transact with (Highnes, Ranjima, etc.)
  - LedgerEntry: a financial event between you and a contact
      entry_type: 'you_sent'   → you gave them money  → balance goes UP (they owe you more)
                  'they_sent'  → they gave you money   → balance goes DOWN
  - Settlement: when a balance is fully or partially cleared
  - PassThrough: you received from A and forwarded to B same day/amount
                 (not counted as your debt in either direction)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from dataclasses import dataclass, field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Contact:
    id: int
    name: str
    upi_id: str | None
    phone: str | None
    notes: str | None
    created_at: str


@dataclass
class LedgerEntry:
    id: int
    contact_id: int
    contact_name: str
    transaction_id: int | None
    entry_type: str          # 'you_sent' | 'they_sent'
    amount: Decimal
    purpose: str | None      # 'loan' | 'rolling' | 'food_split' | 'trip' | 'other'
    notes: str | None
    entry_date: str
    is_opening_balance: bool
    is_passthrough: bool
    passthrough_contact_id: int | None
    created_by: str          # 'user' | 'auto' | 'ai'
    created_at: str


@dataclass
class ContactBalance:
    contact: Contact
    total_you_sent: Decimal
    total_they_sent: Decimal
    total_settled: Decimal
    net_balance: Decimal     # positive = they owe YOU, negative = you owe THEM
    entry_count:
<truncated 13847 bytes>