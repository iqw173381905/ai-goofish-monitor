import asyncio

from src.services.item_analysis_dispatcher import (
    ItemAnalysisDispatcher,
    ItemAnalysisJob,
)


def test_item_analysis_dispatcher_uses_bounded_concurrency():
    active_ai_calls = 0
    max_active_ai_calls = 0
    saved_records = []
    notifications = []

    async def seller_loader(user_id: str):
        await asyncio.sleep(0.005)
        return {"卖家ID": user_id}

    async def image_downloader(product_id: str, image_urls: list[str], task_name: str):
        return []

    async def ai_analyzer(record: dict, image_paths: list[str], prompt_text: str):
        nonlocal active_ai_calls, max_active_ai_calls
        active_ai_calls += 1
        max_active_ai_calls = max(max_active_ai_calls, active_ai_calls)
        await asyncio.sleep(0.03)
        active_ai_calls -= 1
        return {
            "analysis_source": "ai",
            "is_recommended": True,
            "reason": f"推荐 {record['商品信息']['商品ID']}",
            "keyword_hit_count": 0,
        }

    async def notifier(item_data: dict, reason: str):
        notifications.append((item_data["商品ID"], reason))

    async def saver(record: dict, keyword: str):
        saved_records.append((keyword, record))
        return True

    async def run():
        dispatcher = ItemAnalysisDispatcher(
            concurrency=2,
            skip_ai_analysis=False,
            seller_loader=seller_loader,
            image_downloader=image_downloader,
            ai_analyzer=ai_analyzer,
            notifier=notifier,
            saver=saver,
        )
        for index in range(3):
            dispatcher.submit(
                ItemAnalysisJob(
                    keyword="demo",
                    task_name="Demo",
                    decision_mode="ai",
                    analyze_images=False,
                    prompt_text="prompt",
                    keyword_rules=(),
                    final_record={
                        "商品信息": {"商品ID": str(index), "商品图片列表": []},
                        "卖家信息": {},
                    },
                    seller_id=f"seller-{index}",
                    zhima_credit_text="优秀",
                    registration_duration_text="来闲鱼1年",
                )
            )
        await dispatcher.join()
        return dispatcher

    dispatcher = asyncio.run(run())
    assert dispatcher.completed_count == 3
    assert len(saved_records) == 3
    assert len(notifications) == 3
    assert max_active_ai_calls == 2
    assert saved_records[0][1]["卖家信息"]["卖家ID"].startswith("seller-")


def test_item_analysis_dispatcher_supports_keyword_mode_without_ai():
    saved_records = []

    async def seller_loader(user_id: str):
        return {"卖家标签": "个人闲置"}

    async def image_downloader(product_id: str, image_urls: list[str], task_name: str):
        raise AssertionError("关键词模式不应下载图片")

    async def ai_analyzer(record: dict, image_paths: list[str], prompt_text: str):
        raise AssertionError("关键词模式不应调用 AI")

    async def notifier(item_data: dict, reason: str):
        return None

    async def saver(record: dict, keyword: str):
        saved_records.append(record)
        return True

    async def run():
        dispatcher = ItemAnalysisDispatcher(
            concurrency=1,
            skip_ai_analysis=False,
            seller_loader=seller_loader,
            image_downloader=image_downloader,
            ai_analyzer=ai_analyzer,
            notifier=notifier,
            saver=saver,
        )
        dispatcher.submit(
            ItemAnalysisJob(
                keyword="demo",
                task_name="Demo",
                decision_mode="keyword",
                analyze_images=False,
                prompt_text="",
                keyword_rules=("个人闲置",),
                final_record={
                    "商品信息": {"商品ID": "1", "商品标题": "演示商品"},
                    "卖家信息": {},
                },
                seller_id="seller-1",
                zhima_credit_text="优秀",
                registration_duration_text="来闲鱼1年",
            )
        )
        await dispatcher.join()

    asyncio.run(run())
    assert saved_records[0]["ai_analysis"]["analysis_source"] == "keyword"
    assert saved_records[0]["ai_analysis"]["is_recommended"] is True


def _run_single_item_job(*, title: str, ai_recommended: bool):
    """跑一个单商品任务，返回最终保存的记录列表与通知列表。"""
    saved_records = []
    notifications = []

    async def seller_loader(user_id: str):
        return {}

    async def image_downloader(product_id: str, image_urls: list[str], task_name: str):
        return []

    async def ai_analyzer(record: dict, image_paths: list[str], prompt_text: str, image_urls=None):
        return {
            "analysis_source": "ai",
            "is_recommended": ai_recommended,
            "reason": "AI 认为值得推荐",
            "value_score": 85,
        }

    async def notifier(item_data: dict, reason: str):
        notifications.append((item_data["商品ID"], reason))

    async def saver(record: dict, keyword: str):
        saved_records.append(record)
        return True

    async def run():
        dispatcher = ItemAnalysisDispatcher(
            concurrency=1,
            skip_ai_analysis=False,
            seller_loader=seller_loader,
            image_downloader=image_downloader,
            ai_analyzer=ai_analyzer,
            notifier=notifier,
            saver=saver,
        )
        dispatcher.submit(
            ItemAnalysisJob(
                keyword="s3蜂窝国行",
                task_name="s3蜂窝国行",
                decision_mode="ai",
                analyze_images=False,
                prompt_text="prompt",
                keyword_rules=(),
                optional_keywords=("Apple Watch Series 3", "蜂窝版", "A1892", "国行", "42mm"),
                optional_min_hits=3,
                final_record={
                    "商品信息": {"商品ID": "1", "商品标题": title, "商品图片列表": []},
                    "卖家信息": {},
                },
                seller_id="seller-1",
            )
        )
        await dispatcher.join()

    asyncio.run(run())
    return saved_records, notifications


def test_zero_keyword_hits_block_ai_recommendation():
    # 标题与任务关键词毫无关联（搜索污染，如汽车中网混进手表任务）：
    # 即使 AI 给出推荐，零命中兜底也必须拦截，且不发通知
    saved_records, notifications = _run_single_item_job(
        title="奥迪A3L原装前中网，适配21-23款车型，蜂窝格栅设计",
        ai_recommended=True,
    )
    final = saved_records[-1]["ai_analysis"]
    assert final["analysis_source"] == "ai"
    assert final["keyword_hit_count"] == 0
    assert final["is_recommended"] is False
    assert "系统兜底" in final["reason"]
    assert notifications == []


def test_keyword_hits_keep_ai_recommendation_and_backfill_hit_count():
    # 命中关键词的正常商品：AI 推荐保留，且真实命中数回填进 AI 结果
    saved_records, notifications = _run_single_item_job(
        title="苹果手表S3 42mm 国行蜂窝版 A1892 功能正常",
        ai_recommended=True,
    )
    final = saved_records[-1]["ai_analysis"]
    assert final["analysis_source"] == "ai"
    assert final["keyword_hit_count"] >= 3
    assert final["is_recommended"] is True
    assert len(notifications) == 1
