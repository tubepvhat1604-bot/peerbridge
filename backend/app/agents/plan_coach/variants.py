"""Assign once per pair independently of feature flag; callers hold BEGIN IMMEDIATE."""

import hashlib
import secrets


def choose_variant(pair_id, seed=None):
    bit = secrets.randbelow(2) if seed is None else hashlib.sha256(f"{seed}:{pair_id}".encode()).digest()[0] % 2
    return ("ai", "template")[bit]


def assigned_variant(db, pair_id, seed=None):
    existing = db.execute("SELECT variant FROM pb_variants WHERE pair_id=?", (pair_id,)).fetchone()
    if existing:
        return existing[0]
    variant = choose_variant(pair_id, seed)
    db.execute("INSERT OR IGNORE INTO pb_variants(pair_id,variant) VALUES (?,?)", (pair_id, variant))
    return db.execute("SELECT variant FROM pb_variants WHERE pair_id=?", (pair_id,)).fetchone()[0]
