from app.services.standard_field import ClusterCandidate, build_name_clusters


def _row(name: str, urn: str, raw_type: str, logical: str, comment: str | None = None):
    return (name, urn, raw_type, logical, comment)


def test_cluster_prefers_majority_type_and_counts_distribution():
    rows = [
        _row("mobile", "mysql:a:db:t1:mobile", "varchar(20)", "STRING"),
        _row("mobile", "mysql:a:db:t2:mobile", "varchar(20)", "STRING"),
        _row("mobile", "mysql:a:db:t3:mobile", "varchar(11)", "STRING"),
    ]

    clusters = build_name_clusters(rows)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.column_name == "mobile"
    assert cluster.candidate_count == 3
    assert cluster.type_distribution == {"varchar(20)": 2, "varchar(11)": 1}
    assert cluster.recommended_raw_type == "varchar(20)"
    assert cluster.recommended_logical_type == "STRING"
    assert cluster.has_conflict is False
    assert set(cluster.column_urns) == {
        "mysql:a:db:t1:mobile",
        "mysql:a:db:t2:mobile",
        "mysql:a:db:t3:mobile",
    }


def test_cluster_flags_conflict_when_logical_types_differ():
    rows = [
        _row("site_code", "mysql:a:db:t1:site_code", "varchar(16)", "STRING"),
        _row("site_code", "mysql:a:db:t2:site_code", "bigint", "INT"),
    ]

    clusters = build_name_clusters(rows)

    assert clusters[0].has_conflict is True
    assert clusters[0].type_distribution == {"varchar(16)": 1, "bigint": 1}


def test_cluster_prefills_meaning_from_most_common_comment():
    rows = [
        _row("waybill_no", "u1", "varchar(32)", "STRING", "运单号"),
        _row("waybill_no", "u2", "varchar(32)", "STRING", "运单号"),
        _row("waybill_no", "u3", "varchar(32)", "STRING", None),
    ]

    clusters = build_name_clusters(rows)

    assert clusters[0].suggested_meaning == "运单号"


def test_cluster_excludes_blacklisted_names():
    rows = [
        _row("status", "u1", "tinyint", "INT"),
        _row("order_no", "u2", "varchar(32)", "STRING"),
    ]

    clusters = build_name_clusters(rows, excluded_names={"status"})

    assert [c.column_name for c in clusters] == ["order_no"]


def test_clusters_sorted_by_candidate_count_desc():
    rows = [
        _row("rare_field", "u1", "varchar(8)", "STRING"),
        *(_row("common_field", f"u{i}", "varchar(8)", "STRING") for i in range(2, 6)),
    ]

    clusters = build_name_clusters(rows)

    assert [c.column_name for c in clusters] == ["common_field", "rare_field"]
    assert all(isinstance(c, ClusterCandidate) for c in clusters)


def test_doc_only_field_name_still_produces_candidate():
    # Excel 里有、源库还没同步的字段名同样产出候选（标准可先定，表后接）
    doc_rows = [
        ("site_type_code", "varchar(16)", "网点类型编号"),
        ("site_type_code", "varchar(16)", "网点类型"),
    ]

    clusters = build_name_clusters([], doc_rows)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.column_name == "site_type_code"
    assert cluster.candidate_count == 0
    assert cluster.doc_count == 2
    assert cluster.recommended_raw_type == "varchar(16)"
    assert cluster.recommended_logical_type == "STRING"
    assert cluster.suggested_meaning in {"网点类型编号", "网点类型"}
    assert cluster.column_urns == []


def test_sync_and_doc_evidence_merge_into_one_distribution():
    sync_rows = [_row("waybill_no", f"u{i}", "varchar(32)", "STRING", "运单编号") for i in range(3)]
    doc_rows = [("waybill_no", "varchar(16)", "运单号")]

    clusters = build_name_clusters(sync_rows, doc_rows)

    cluster = clusters[0]
    assert cluster.candidate_count == 3
    assert cluster.doc_count == 1
    assert cluster.type_distribution == {"varchar(32)": 3, "varchar(16)": 1}
    assert cluster.recommended_raw_type == "varchar(32)"
    assert cluster.suggested_meaning == "运单编号"


def test_doc_type_conflict_with_sync_marks_conflict():
    sync_rows = [_row("site_code", "u1", "varchar(16)", "STRING", "网点编号")]
    doc_rows = [("site_code", "bigint", "网点编号")]

    clusters = build_name_clusters(sync_rows, doc_rows)

    # 冲突判定在聚类层；推荐类型置空由 generate 环节处理（强制人工裁决）
    assert clusters[0].has_conflict is True
    assert clusters[0].type_distribution == {"varchar(16)": 1, "bigint": 1}
