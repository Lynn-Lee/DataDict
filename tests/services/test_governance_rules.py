"""同步后治理的决策规则（脱库单测）。

挂载与待办的判断都抽成纯函数，数据库只负责取数与写入，
这样「注释变更怎么重挂」「缺口什么时候不再提醒」这两条容易被改坏的口径有测试兜着。
"""

from app.services.governance import decide_attachment, plan_missing_todo


def test_unlinked_column_with_matching_standard_is_attached():
    assert (
        decide_attachment(attached_standard_id=None, attached_sub_key="", expected_standard_id=11)
        == "ATTACH"
    )


def test_unlinked_column_without_any_standard_stays_put():
    assert (
        decide_attachment(attached_standard_id=None, attached_sub_key="", expected_standard_id=None)
        == "KEEP"
    )


def test_comment_change_detaches_from_meaning_group_but_not_from_name_level_standard():
    """释义级标准的成员定义就是释义哈希；名级标准下的关联可能是人工异名归组，不能推翻。"""
    assert (
        decide_attachment(
            attached_standard_id=21, attached_sub_key="abc", expected_standard_id=None
        )
        == "DETACH"
    )
    assert (
        decide_attachment(attached_standard_id=21, attached_sub_key="", expected_standard_id=None)
        == "KEEP"
    )


def test_meaning_group_change_moves_between_split_standards():
    assert (
        decide_attachment(attached_standard_id=21, attached_sub_key="abc", expected_standard_id=22)
        == "MOVE"
    )
    assert (
        decide_attachment(attached_standard_id=21, attached_sub_key="abc", expected_standard_id=21)
        == "KEEP"
    )


def test_missing_todo_opens_when_gap_appears():
    assert (
        plan_missing_todo(gap_count=5, open_missing_count=None, last_closed_missing_count=None)
        == "CREATE"
    )


def test_missing_todo_refreshes_open_count_only_when_it_changes():
    assert (
        plan_missing_todo(gap_count=5, open_missing_count=5, last_closed_missing_count=None)
        == "KEEP"
    )
    assert (
        plan_missing_todo(gap_count=3, open_missing_count=5, last_closed_missing_count=None)
        == "REFRESH"
    )


def test_exempted_table_is_not_reopened_unless_gap_grows():
    """豁免机制不能被每轮扫描复活：缺口没变大就闭嘴，恶化了才重开一条。"""
    assert (
        plan_missing_todo(gap_count=4, open_missing_count=None, last_closed_missing_count=4)
        == "SILENT"
    )
    assert (
        plan_missing_todo(gap_count=2, open_missing_count=None, last_closed_missing_count=4)
        == "SILENT"
    )
    assert (
        plan_missing_todo(gap_count=5, open_missing_count=None, last_closed_missing_count=4)
        == "CREATE"
    )


def test_missing_todo_auto_closes_when_gap_is_gone():
    assert (
        plan_missing_todo(gap_count=0, open_missing_count=3, last_closed_missing_count=None)
        == "CLOSE"
    )
    assert (
        plan_missing_todo(gap_count=0, open_missing_count=None, last_closed_missing_count=3)
        == "KEEP"
    )
