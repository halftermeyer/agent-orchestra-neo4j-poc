import json

from orchestra.gateway.keystore import KeyStore
from tests.conftest import tok


def test_kg_templates_and_rights(client, world):
    a, b = world.agent("t-a", kgs=["produit"]), world.agent("t-b")
    q = lambda who, kg, t, params=None: world.post("/kg/query", who, {"kg": kg, "template": t, "params": params or {}})
    r = q(a, "produit", "part_info", {"partId": "PRT-0001"})
    assert r.status_code == 200 and r.json()["rows"][0]["name"].startswith("Station")
    assert len(q(a, "produit", "part_children", {"partId": "PRT-0001"}).json()["rows"]) == 6
    shared = q(a, "produit", "part_where_used", {"partId": "PRT-0045"}).json()["rows"]
    assert shared and shared[0]["level"] >= 2 and any(x["level"] == 0 for x in shared)
    assert q(a, "produit", "part_tests", {"partId": "PRT-0045"}).status_code == 200
    assert len(q(a, "produit", "replacement_candidates", {"partId": "PRT-0045", "limit": 3}).json()["rows"]) == 3
    assert q(b, "produit", "part_info", {"partId": "PRT-0001"}).status_code == 403          # pas de CAN_QUERY
    assert q(a, "projet", "project_graph").status_code == 403                                 # autre KG
    assert q(a, "produit", "inconnu").status_code == 404
    assert q(a, "produit", "part_info", {"partId": "x", "cypher": "MATCH (n) RETURN n"}).status_code == 403
    assert q(a, "produit", "part_info", {"partId": 12}).status_code == 403
    assert q(a, "projet", "part_info", {"partId": "PRT-0001"}).status_code == 403             # mauvais graphe pour le modèle


def test_federated_query_needs_both_graphs(client, world):
    one, both = world.agent("t-one", kgs=["produit"]), world.agent("t-both", kgs=["produit", "projet"])
    body = {"template": "impact_part", "params": {"partId": "PRT-0045"}}
    assert world.post("/kg/federated", one, body).status_code == 403
    r = world.post("/kg/federated", both, body)
    assert r.status_code == 200, r.text
    row = r.json()["rows"][0]
    assert isinstance(row["testIds"], list) and isinstance(row["tasks"], list)
    assert world.post("/kg/federated", both, {"template": "x", "params": {}}).status_code == 404


def test_model_settings_are_write_only_and_encrypted(client, world):
    ctx = client.ctx
    ctx.keystore.delete()
    h = tok("admin")
    a = world.agent("t-a")
    assert client.get("/settings/models", headers=tok("svc", a)).status_code == 403
    assert client.get("/settings/models", headers=h).json()["configured"] is False
    secret = "test-SECRET-VALUE-9876"
    r = client.put("/settings/models/key", json={"apiKey": secret}, headers=h)
    assert r.status_code == 200 and secret not in r.text
    st = client.get("/settings/models", headers=h)
    assert secret not in st.text and st.json()["last4"] == "9876" and st.json()["source"] == "ui" and st.json()["updatedAt"]
    assert secret not in ctx.keystore.file.read_text()                      # chiffré sur disque
    assert ctx.keystore.get() == secret
    t = client.post("/settings/models/test", json={}, headers=h).json()
    assert t["ok"] and "fake-model-a" in t["models"] and secret not in json.dumps(t)
    assert client.put("/settings/models/selection", json={"model": "fake-model-a"}, headers=h).json() == {"model": "fake-model-a"}
    assert client.get("/settings/models", headers=h).json()["model"] == "fake-model-a"
    assert client.put("/settings/models/key", json={"apiKey": "test-REPLACED-0001"}, headers=h).json()["last4"] == "0001"
    assert client.delete("/settings/models/key", headers=h).json()["configured"] is False
    # sans clé, rappel mémoire et génération refusés proprement
    ctx.keystore.delete()
    assert world.post("/recall", a, {"query": "x"}).status_code == 409


def test_ui_key_has_priority_over_env_initial_value(tmp_path):
    ks = KeyStore(tmp_path, "m", env_key="ENVKEY-1111")
    assert ks.get() == "ENVKEY-1111" and ks.status()["source"] == "env"
    ks.set("UIKEY-2222")
    assert ks.get() == "UIKEY-2222" and ks.status()["source"] == "ui" and ks.status()["last4"] == "2222"
    ks.delete()
    assert ks.get() == "ENVKEY-1111"
    # une autre clé maître ne déchiffre pas
    ks.set("UIKEY-3333")
    assert KeyStore(tmp_path, "autre-maitre").status()["configured"] is True
    try:
        KeyStore(tmp_path, "autre-maitre").get()
        assert False
    except Exception as e:
        assert "UIKEY" not in str(e)


def test_llm_generate_is_governed(client, world, fake, tq):
    a = world.agent("t-a", tools=["recall", "set_status"])
    sid = world.session(a, chain="c-llm")
    body = {"sessionId": sid, "contents": [{"role": "user", "text": "salut"}], "system": "tu es A", "tools": ["recall"]}
    r = world.post("/llm/generate", a, body)
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "ok" and r.json()["usage"] == {"input": 10, "output": 5}
    assert fake.calls[-1] == {"model": "fake-model", "system": "tu es A", "tools": ["recall"]}      # modèle de l'AgentVersion
    assert tq("MATCH (c:Chain {id: 'c-llm'}) RETURN c.tokensSpent AS t")[0]["t"] == 15
    assert world.post("/llm/generate", a, {**body, "tools": ["send_message"]}).status_code == 403   # pas de CAN_USE
    assert world.post("/llm/generate", a, {**body, "model": "gemini-x"}).status_code == 422          # le modèle n'est pas un argument
    fake.next_tool_calls = [("recall", {"query": "x"})]
    r = world.post("/llm/generate", a, body)
    assert r.json()["toolCalls"] == [{"name": "recall", "args": {"query": "x"}}]


def test_llm_token_budget_suspends_chain(client, world, tq):
    a = world.agent("t-a")
    client.post("/chains", json={"id": "c-tok", "budget": 10, "tokenBudget": 20}, headers=tok("admin"))
    sid = world.session(a, chain="c-tok")
    body = {"sessionId": sid, "contents": [{"role": "user", "text": "x"}]}
    assert world.post("/llm/generate", a, body).status_code == 200     # 15/20
    assert world.post("/llm/generate", a, body).status_code == 200     # 30/20 -> suspendue
    assert tq("MATCH (c:Chain {id: 'c-tok'}) RETURN c.status AS s, c.suspendReason AS r")[0] == {"s": "suspended", "r": "tokens"}
    assert world.post("/llm/generate", a, body).status_code == 409


def test_rule_agent_has_no_model(client, world, tq):
    a = world.agent("t-rule")
    tq("MATCH (:Agent {id: 't-rule'})-[:CURRENT]->(v) SET v.kind = 'rule', v.model = null")
    sid = world.session(a)
    r = world.post("/llm/generate", a, {"sessionId": sid, "contents": [{"role": "user", "text": "x"}]})
    assert r.status_code == 409
