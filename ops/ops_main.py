# -*- coding: utf-8 -*-
"""主调度器：协调采集→清洗→蒸馏→优化→快照→报告全流程"""
import os
import sys
import time
import json
import traceback

# 确保能导入项目根目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ops_db
import collector
import cleaner
import optimizer
import version
import reporter
import db
import pipeline


def run_ops(uid=0, task_name="daily_ops"):
    """执行完整的运维流程"""
    run_id = ops_db.start_task_run(task_name)
    ops_db.log_change("ops_run", run_id, "started", task_run_id=run_id)

    results = {
        "collect": {}, "clean": {}, "distill": {}, "optimize": {},
        "snapshot": {}, "digest": {}
    }

    try:
        # ========== 1. 采集 ==========
        sources = ops_db.get_sources(enabled_only=True)
        if sources:
            items, created = collector.collect_all(uid, sources)
            results["collect"] = {"sources_fetched": len(sources), "items_fetched": items, "items_created": created}
            ops_db.log_change("collect", run_id, "completed",
                           old_value=str(len(sources)), new_value=str(items),
                           reason=f"采集{len(sources)}个源，新增{created}条", task_run_id=run_id)
        else:
            results["collect"] = {"sources_fetched": 0, "items_fetched": 0, "items_created": 0}

        # ========== 2. 清洗 ==========
        clean_result = cleaner.run_cleaning(uid, run_id)
        results["clean"] = clean_result

        # ========== 3. 蒸馏（将采集的内容蒸馏为知识卡片）===========
        conn = db.get_conn()
        pending_captures = conn.execute("SELECT id FROM captures WHERE user_id=? AND status='pending'", (uid,)).fetchall()
        conn.close()
        distilled = 0
        for cap in pending_captures:
            result = pipeline.distill_capture(uid, cap["id"])
            if result and result.get("cards"):
                distilled += 1
            else:
                # 蒸馏失败也要更新状态
                conn = db.get_conn()
                conn.execute("UPDATE captures SET status='distilled' WHERE id=?", (cap["id"],))
                conn.close()
        results["distill"] = {"pending_count": len(pending_captures), "distilled": distilled}

        # ========== 4. 优化 ==========
        opt_result = optimizer.run_optimization(uid, run_id)
        results["optimize"] = opt_result

        # ========== 5. 快照 ==========
        today = time.strftime("%Y%m%d")
        version_tag = f"v{today}_{int(time.time())}"
        snap = version.create_snapshot(uid, version_tag, f"每日运维快照 {time.strftime('%Y-%m-%d %H:%M')}")
        results["snapshot"] = snap

        # ========== 6. 报告 ==========
        digest = reporter.generate_daily_digest(uid, run_id, results["collect"], results["clean"], results["optimize"], results["snapshot"])
        results["digest"] = digest

        # 完成
        ops_db.finish_task_run(
            run_id, "success",
            items_processed=items, items_created=created,
            items_duplicated=clean_result.get("duplicates_found", 0),
            items_deleted=clean_result.get("expired_found", 0),
            error_count=0,
            summary=f"采集{created}条，去重{clean_result.get('duplicates_found',0)}条，过期{clean_result.get('expired_found',0)}条，蒸馏{distilled}条，优化{opt_result.get('quality',{}).get('updated',0)}张"
        )
        ops_db.log_change("ops_run", run_id, "completed", task_run_id=run_id)

    except Exception as e:
        traceback.print_exc()
        ops_db.finish_task_run(run_id, "error", error_count=1, summary=str(e))
        ops_db.log_change("ops_run", run_id, "error", new_value=str(e), task_run_id=run_id)
        results["error"] = str(e)

    return results


def run_quick_ops(uid=0):
    """快速运维：只做清洗+优化+快照，跳过采集"""
    run_id = ops_db.start_task_run("quick_ops")
    results = {}

    try:
        clean_result = cleaner.run_cleaning(uid, run_id)
        results["clean"] = clean_result

        opt_result = optimizer.run_optimization(uid, run_id)
        results["optimize"] = opt_result

        ops_db.finish_task_run(run_id, "success",
                              items_duplicated=clean_result.get("duplicates_found", 0),
                              items_deleted=clean_result.get("expired_found", 0),
                              summary=f"快速运维：去重{clean_result.get('duplicates_found',0)}条，过期{clean_result.get('expired_found',0)}条")
    except Exception as e:
        ops_db.finish_task_run(run_id, "error", error_count=1, summary=str(e))
        results["error"] = str(e)

    return results


if __name__ == "__main__":
    ops_db.init_db()
    # 默认使用 dev 用户
    uid = db.ensure_dev_user()
    results = run_ops(uid)
    print(json.dumps(results, ensure_ascii=False, indent=2))
