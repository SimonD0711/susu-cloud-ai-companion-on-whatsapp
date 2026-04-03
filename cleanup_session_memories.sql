-- ============================================================
-- 苏苏短期记忆清理脚本
-- 使用方法：
--   1. 先执行第一部分（SELECT）查看要清理的内容
--   2. 确认无误后执行第二部分（DELETE）
-- ============================================================

-- ============================================================
-- 第1部分：查看噪音记忆（只读，不删除）
-- ============================================================

-- 1.1 查看所有短期记忆（按更新时间倒序）
-- SELECT id, wa_id, bucket, content, observed_at, updated_at, expires_at, use_count
-- FROM wa_session_memories
-- ORDER BY updated_at DESC
-- LIMIT 100;

-- 1.2 查找超短内容（可能是噪音）
-- SELECT id, bucket, length(content) as len, content
-- FROM wa_session_memories
-- WHERE length(content) < 5
-- ORDER BY id;

-- 1.3 查找纯问候/客套句
-- SELECT id, content, bucket
-- FROM wa_session_memories
-- WHERE content IN ('hi', 'hello', '你好', '早晨', '晚安', 'thank you', '謝謝', '好', 'ok', 'OK', '好呀', '好吖')
--    OR content LIKE '好%'
--    OR content LIKE 'hi%'
--    OR content LIKE 'hello%';

-- 1.4 查找重复记忆（同一 bucket 相同 content）
-- SELECT bucket, content, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
-- FROM wa_session_memories
-- GROUP BY bucket, content
-- HAVING cnt > 1
-- ORDER BY cnt DESC;

-- 1.5 按 bucket 统计数量
-- SELECT bucket, COUNT(*) as cnt FROM wa_session_memories GROUP BY bucket;

-- 1.6 查看已过期的记忆
-- SELECT id, content, expires_at FROM wa_session_memories
-- WHERE expires_at < datetime('now')
-- LIMIT 50;

-- ============================================================
-- 第2部分：清理操作（确认后再执行）
-- ============================================================

-- 2.1 删除超短内容（<4字符，排除有意义的时间标记如"今日"、"尋晚"）
-- DELETE FROM wa_session_memories
-- WHERE length(content) < 4
--   AND content NOT IN ('今日', '昨晚', '尋晚', '聽日', '今日', '琴晚', '昨日', '聽日', '明天', '今晚', '今朝');

-- 2.2 删除纯问候/客套句
-- DELETE FROM wa_session_memories
-- WHERE content IN ('hi', 'hello', '你好', '早晨', '晚安', 'thank you', '謝謝', '好', 'ok', 'OK', '好呀', '好吖');

-- 2.3 删除完全重复的记忆（保留最新一条）
-- DELETE FROM wa_session_memories
-- WHERE id IN (
--     SELECT id FROM wa_session_memories
--     WHERE (bucket, content, wa_id) IN (
--         SELECT bucket, content, wa_id FROM wa_session_memories
--         GROUP BY bucket, content, wa_id
--         HAVING COUNT(*) > 1
--     )
--     AND id NOT IN (
--         SELECT MAX(id) FROM wa_session_memories
--         GROUP BY bucket, content, wa_id
--         HAVING COUNT(*) > 1
--     )
-- );

-- 2.4 删除已过期记忆
-- DELETE FROM wa_session_memories
-- WHERE expires_at < datetime('now');

-- 2.5 查看最终统计
-- SELECT
--     (SELECT COUNT(*) FROM wa_session_memories) as total,
--     (SELECT COUNT(*) FROM wa_session_memories WHERE bucket = 'within_24h') as within_24h,
--     (SELECT COUNT(*) FROM wa_session_memories WHERE bucket = 'within_3d') as within_3d,
--     (SELECT COUNT(*) FROM wa_session_memories WHERE bucket = 'within_7d') as within_7d,
--     (SELECT COUNT(*) FROM wa_session_memories WHERE expires_at < datetime('now')) as expired;
