from booklayout.recover_top import SrcLine, recover_gaps


def _ln(t):
    return SrcLine(page=1, line=0, text=t, conf=95.0, box=(0, 0, 1, 1))


def test_uncovered_run_reinserted_between_blocks():
    lines = [_ln("Texto inicial de la pagina"), _ln("do comprobar que existen especies herbivoras"),
             _ln("y fragmentos de macroalgas y otras"), _ln("Los Silidos son parasitados por otros")]
    data = {"pages": [{"page": 36, "blocks": [
        {"block_id": "p036_b00", "role": "body", "text": "Texto inicial de la pagina"},
        {"block_id": "p036_b03", "role": "body", "text": "Los Silidos son parasitados por otros"}]}]}
    done = recover_gaps(data, {36: lines})
    assert len(done) == 1
    ids = [b["block_id"] for b in data["pages"][0]["blocks"]]
    assert ids[0] == "p036_b00" and ids[2] == "p036_b03" and ids[1].startswith("p036_g")
    assert data["pages"][0]["blocks"][1]["text"].startswith("do comprobar")


def test_short_run_after_figure_legend_is_appended_to_it():
    lines = [_ln("Fig. 11. Ejemplar de Syllis"), _ln("de un fragmento con ovulos"), _ln("spongicola (B).")]
    data = {"pages": [{"page": 1, "blocks": [{"block_id": "b0", "role": "body", "text": "Fig. 11. Ejemplar de Syllis"}]}]}
    recover_gaps(data, {1: lines})
    assert len(data["pages"][0]["blocks"]) == 1
    assert data["pages"][0]["blocks"][0]["text"].endswith("spongicola (B).")


def test_covered_lines_not_duplicated():
    lines = [_ln("Los Silidos son parasitados por otros"), _ln("y fragmentos de macroalgas y otras")]
    data = {"pages": [{"page": 1, "blocks": [{"block_id": "b0", "role": "body",
            "text": "Los Silidos son parasitados por otros y fragmentos de macroalgas y otras"}]}]}
    assert recover_gaps(data, {1: lines}) == []
