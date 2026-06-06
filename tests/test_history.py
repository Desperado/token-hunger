from costbench.history import (
    MIN_SAMPLES,
    Observation,
    append_observations,
    append_unique_observations,
    load_observations,
    percentiles_for,
)


def _obs(cf, tid, itok, otok):
    return Observation(
        config_fingerprint=cf,
        target_id=tid,
        model_id=tid,
        input_tokens=itok,
        output_tokens=otok,
        cost=0.001,
        passed=True,
        ts="2026-06-06T00:00:00Z",
    )


def test_roundtrip_append_and_load(tmp_path):
    p = tmp_path / "history.jsonl"
    obs = [_obs("cfg1", "openai/gpt-5", 100, 50), _obs("cfg1", "openai/gpt-5", 200, 80)]
    append_observations(obs, path=p)
    loaded = load_observations(path=p)
    assert len(loaded) == 2
    assert loaded[0].input_tokens == 100
    assert loaded[1].output_tokens == 80


def test_malformed_lines_skipped(tmp_path):
    p = tmp_path / "history.jsonl"
    append_observations([_obs("cfg1", "t", 10, 10)], path=p)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("this is not json\n")
        fh.write('{"missing":"fields"}\n')
    loaded = load_observations(path=p)
    assert len(loaded) == 1


def test_percentiles_gate_below_min_samples(tmp_path):
    p = tmp_path / "history.jsonl"
    obs = [_obs("cfg1", "t", i, i) for i in range(MIN_SAMPLES - 1)]
    append_observations(obs, path=p)
    loaded = load_observations(path=p)
    assert percentiles_for(loaded, "cfg1", "t") is None


def test_percentiles_nearest_rank_round_up():
    obs = [_obs("cfg1", "t", v, v * 2) for v in [10, 20, 30, 40, 50]]
    pct = percentiles_for(obs, "cfg1", "t")
    assert pct is not None
    assert pct.n == 5
    # nearest-rank p50: ceil(0.5*5)=3 -> 3rd value = 30
    assert pct.input_p50 == 30
    # p90: ceil(0.9*5)=5 -> 5th value = 50
    assert pct.input_p90 == 50
    assert pct.output_p90 == 100


def test_load_missing_file_returns_empty(tmp_path):
    assert load_observations(path=tmp_path / "nope.jsonl") == []


def test_unique_append_deduplicates_stable_observation_ids(tmp_path):
    p = tmp_path / "history.jsonl"
    observation = Observation(
        config_fingerprint="cfg1",
        target_id="target",
        model_id="model",
        input_tokens=10,
        output_tokens=2,
        cost=0.01,
        passed=False,
        ts="2026-06-06T00:00:00Z",
        observation_id="external:cfg1:row-1",
        source="external",
        schema_version=2,
    )

    assert append_unique_observations([observation, observation], path=p) == 1
    assert append_unique_observations([observation], path=p) == 0
    assert len(load_observations(path=p)) == 1


def test_old_history_rows_get_source_defaults(tmp_path):
    p = tmp_path / "history.jsonl"
    p.write_text(
        '{"config_fingerprint":"cfg","target_id":"t","model_id":"m",'
        '"input_tokens":1,"output_tokens":2,"cost":0.1,"passed":true,"ts":"x"}\n',
        encoding="utf-8",
    )

    loaded = load_observations(path=p)
    assert loaded[0].observation_id == ""
    assert loaded[0].source == "run"
