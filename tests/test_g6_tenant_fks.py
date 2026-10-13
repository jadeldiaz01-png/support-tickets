"""G6: exhaustive negative coverage for each original FK relationship.

All database reads/writes run against disposable CI service. Direct SQL writes
from the restricted runtime role must fail on cross-tenant references. These
are new validated constraints, not claims about real production instances.
"""
from __future__ import annotations

import os
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from repositories.db import bind_tenant,get_engine

OWNER_URL=os.environ.get("DATABASE_URL_OWNER")
pytestmark=pytest.mark.skipif(not OWNER_URL,reason="Disposable PostgreSQL CI only")

REFERENCES=(
    ("ticket_assignments","tickets","ticket_id",True),
    ("ticket_assignments","users","user_id",True),
    ("approval_requests","users","decided_by",False),
    ("approval_requests","users","requested_by",False),
    ("approval_requests","tickets","ticket_id",False),
    ("reconciliation_records","tool_intents","intent_id",False),
    ("ticket_events","tickets","ticket_id",False),
    ("ticket_messages","users","author_user_id",False),
    ("ticket_messages","tickets","ticket_id",False),
    ("ticket_sla_state","tickets","ticket_id",False),
    ("ticket_tags","tickets","ticket_id",False),
    ("tickets","customers","customer_id",False),
    ("tool_intents","tickets","ticket_id",False),
)

@pytest.fixture
def tenants(monkeypatch):
    monkeypatch.setenv("SUPPORT_ENV","test")
    monkeypatch.setenv("SUPPORT_AUTH_MODE","test-header")
    monkeypatch.setenv("SUPPORT_POLICY_MODE","test-local")
    ids={n:uuid4() for n in (
        "ta","tb","ua","ub","ca","cb","ticket_a","ticket_b","intent_a","intent_b"
    )}
    e=create_engine(OWNER_URL,future=True)
    with e.begin() as c:
        c.execute(text("""
            TRUNCATE TABLE reconciliation_records,outbox_events,tool_intents,
                approval_requests,ticket_sla_state,ticket_tags,ticket_assignments,
                ticket_events,ticket_messages,audit_events,knowledge_sources,
                tickets,customers,users,tenants CASCADE
        """))
        c.execute(text("INSERT INTO tenants(id,slug) VALUES (:ta,'g6-test-a'),(:tb,'g6-test-b')"),ids)
        c.execute(text("""
            INSERT INTO users(id,tenant_id,external_subject,role)
            VALUES (:ua,:ta,'g6-ua','SUPPORT_AGENT'),(:ub,:tb,'g6-ub','SUPPORT_AGENT')
        """),ids)
        c.execute(text("""
            INSERT INTO customers(id,tenant_id,external_ref)
            VALUES (:ca,:ta,'a'),(:cb,:tb,'b')
        """),ids)
        c.execute(text("""
            INSERT INTO tickets(id,tenant_id,customer_id,idempotency_key,subject)
            VALUES (:ticket_a,:ta,:ca,'g6-a','ticket-a'),
                   (:ticket_b,:tb,:cb,'g6-b','ticket-b')
        """),ids)
        c.execute(text("""
            INSERT INTO tool_intents(
              id,tenant_id,ticket_id,tool_name,idempotency_key
            ) VALUES
              (:intent_a,:ta,:ticket_a,'offline','g6-intent-a'),
              (:intent_b,:tb,:ticket_b,'offline','g6-intent-b')
        """),ids)
    e.dispose()
    return ids

def forged(child,col, ids):
    local={"tenant_id":ids["tb"]}
    foreign={
        "users":ids["ua"],"tickets":ids["ticket_a"],
        "customers":ids["ca"],"tool_intents":ids["intent_a"],
    }
    table={
        "ticket_assignments":("id,ticket_id,user_id",{
            "id":uuid4(),"ticket_id":ids["ticket_b"],"user_id":ids["ub"]}),
        "approval_requests":("id,action",{
            "id":uuid4(),"action":"g6-test"}),
        "reconciliation_records":("id,state",{
            "id":uuid4(),"state":"UNKNOWN"}),
        "ticket_events":("id,ticket_id,event_type",{
            "id":uuid4(),"ticket_id":ids["ticket_b"],"event_type":"G6_TEST"}),
        "ticket_messages":("id,ticket_id,author_type,body",{
            "id":uuid4(),"ticket_id":ids["ticket_b"],
            "author_type":"HUMAN_AGENT","body":"test only"}),
        "ticket_sla_state":("ticket_id",{"ticket_id":ids["ticket_b"]}),
        "ticket_tags":("id,ticket_id,tag",{
            "id":uuid4(),"ticket_id":ids["ticket_b"],"tag":"test"}),
        "tickets":("id,idempotency_key,subject",{
            "id":uuid4(),"idempotency_key":"g6-foreign",
            "subject":"negative test"}),
        "tool_intents":("id,tool_name,idempotency_key",{
            "id":uuid4(),"tool_name":"g6-test","idempotency_key":"g6-take"}),
    }
    _,values=table[child]
    local.update(values)
    parent=next(r[1] for r in REFERENCES if r[0]==child and r[2]==col)
    local[col]=foreign[parent]
    columns=sorted(local)
    sql=(
        f"INSERT INTO {child} ("+",".join(columns)+") VALUES ("+
        ",".join(":"+c for c in columns)+")"
    )
    return sql,local

@pytest.mark.parametrize("child,parent,col,already",REFERENCES)
def test_g6_all_13_foreign_tenant_references_fail(child,parent,col,already,tenants):
    sql,params=forged(child,col,tenants)
    expected_fk = (
        "fk_assignments_tenant_ticket" if already and col == "ticket_id"
        else "fk_assignments_tenant_user" if already
        else f"g6_fk_{child}_{col}"
    )
    with Session(get_engine()) as session:
        with pytest.raises(IntegrityError) as rejected:
            with session.begin():
                bind_tenant(session, tenants["tb"])
                session.execute(text(sql), params)
    # A 23503 from *the intended tenant-scoped FK* is evidence of isolation;
    # an unrelated NOT NULL/CHECK/UNIQUE violation must NOT be counted.
    assert rejected.value.orig.sqlstate == "23503"
    assert rejected.value.orig.diag.constraint_name == expected_fk

def _expected_g61_fk_contract():
    # Each FK is identified by its own unique constraint name, including
    # multiple distinct references to users from the same child table.
    expected = {}
    for child, parent, col, already in REFERENCES:
        name = (
            ("fk_assignments_tenant_ticket" if col == "ticket_id"
             else "fk_assignments_tenant_user")
            if already else f"g6_fk_{child}_{col}"
        )
        assert name not in expected
        expected[name] = {
            "child_name": child,
            "parent_name": parent,
            "pairs": (("tenant_id", "tenant_id"), (col, "id")),
        }
    assert len(expected) == 13
    return expected


def _assert_g61_fk_catalog(rows):
    expected = _expected_g61_fk_contract()
    names = [row["conname"] for row in rows]
    assert len(names) == 13
    assert set(names) == set(expected)
    assert len(names) == len(set(names))
    for row in rows:
        contract = expected[row["conname"]]
        assert row["child_name"] == contract["child_name"]
        assert row["parent_name"] == contract["parent_name"]
        assert row["convalidated"] is True
        local = list(row["local_columns"])
        remote = list(row["parent_columns"])
        assert len(local) == 2 and len(remote) == 2
        # conkey[i] -> confkey[i], not mere presence of 'tenant_id'
        # on a child FK's conkey. The order is declared by the migration.
        assert tuple(zip(local, remote, strict=True)) == contract["pairs"]


def _synthetic_catalog():
    # Pure negative test of the TEST ASSERTION (a wrong column mapping
    # must not be accepted even if tenant_id appears in conkey).
    return [
        {
            "conname": name,
            "child_name": contract["child_name"],
            "parent_name": contract["parent_name"],
            "convalidated": True,
            "local_columns": [p[0] for p in contract["pairs"]],
            "parent_columns": [p[1] for p in contract["pairs"]],
        }
        for name, contract in _expected_g61_fk_contract().items()
    ]


def test_g61_catalog_assertion_accepts_only_exact_column_pairs():
    _assert_g61_fk_catalog(_synthetic_catalog())


def test_g61_catalog_assertion_rejects_tenant_mapping_to_parent_id():
    synthetic = _synthetic_catalog()
    # Still includes tenant_id locally: the old boolean check passed this.
    synthetic[0]["parent_columns"] = ["id", "tenant_id"]
    with pytest.raises(AssertionError):
        _assert_g61_fk_catalog(synthetic)


def test_g61_catalog_assertion_rejects_unvalidated_or_missing_fk():
    rows = _synthetic_catalog()
    rows[0]["convalidated"] = False
    with pytest.raises(AssertionError):
        _assert_g61_fk_catalog(rows)
    with pytest.raises(AssertionError):
        _assert_g61_fk_catalog(_synthetic_catalog()[:-1])


def test_g6_catalog_has_no_plain_cross_tenant_fk_edges(tenants):
    owner = create_engine(OWNER_URL, future=True)
    with owner.connect() as conn:
        rows = conn.execute(text("""
            SELECT child.relname AS child_name,
                   parent.relname AS parent_name,
                   con.conname AS conname,
                   con.convalidated AS convalidated,
                   ARRAY(
                       SELECT ca.attname
                       FROM unnest(con.conkey) WITH ORDINALITY
                            AS key(child_attnum, position)
                       JOIN pg_attribute ca
                         ON ca.attrelid=con.conrelid
                        AND ca.attnum=key.child_attnum
                       ORDER BY key.position
                   ) AS local_columns,
                   ARRAY(
                       SELECT pa.attname
                       FROM unnest(con.confkey) WITH ORDINALITY
                            AS key(parent_attnum, position)
                       JOIN pg_attribute pa
                         ON pa.attrelid=con.confrelid
                        AND pa.attnum=key.parent_attnum
                       ORDER BY key.position
                   ) AS parent_columns
            FROM pg_constraint con
            JOIN pg_class child ON child.oid=con.conrelid
            JOIN pg_class parent ON parent.oid=con.confrelid
            WHERE con.contype='f'
              AND child.relnamespace='public'::regnamespace
              AND parent.relname <> 'tenants'
              AND EXISTS (
                  SELECT 1 FROM pg_attribute a
                  WHERE a.attrelid=con.conrelid
                    AND a.attname='tenant_id'
                    AND NOT a.attisdropped
              )
            ORDER BY child.relname, con.conname
        """)).mappings().all()
    owner.dispose()
    _assert_g61_fk_catalog(rows)


def test_g6_nullable_ref_on_delete_only_nulls_ref_not_tenant(tenants):
    owner=create_engine(OWNER_URL,future=True)
    with owner.begin() as c:
        # The customer and author are optional; ON DELETE SET NULL must
        # preserve tenant_id, not null the compound FK tenant component.
        msg_id=uuid4()
        c.execute(text("""
           INSERT INTO ticket_messages(
             id,tenant_id,ticket_id,author_user_id,author_type,body
           ) VALUES (:id,:tb,:ticket_b,:ub,'HUMAN_AGENT','g6-note')
        """),{**tenants,"id":msg_id})
        c.execute(text("DELETE FROM users WHERE id=:ub"),tenants)
        row=c.execute(text("""
           SELECT tenant_id,author_user_id FROM ticket_messages WHERE id=:id
        """),{"id":msg_id}).one()
        assert row.tenant_id==tenants["tb"]
        assert row.author_user_id is None
        c.execute(text("DELETE FROM customers WHERE id=:cb"),tenants)
        row=c.execute(text("""
           SELECT tenant_id,customer_id FROM tickets WHERE id=:ticket_b
        """),tenants).one()
        assert row.tenant_id==tenants["tb"]
        assert row.customer_id is None
    owner.dispose()
