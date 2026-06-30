-- 加性扩展 events.message_type CHECK，纳入 Plan-Execute 的新事件类型（幂等）。
ALTER TABLE events DROP CONSTRAINT IF EXISTS events_message_type_check;
ALTER TABLE events ADD CONSTRAINT events_message_type_check
    CHECK (message_type IN (
        'tool_thought', 'tool_call', 'tool_result', 'result',
        'plan_thought', 'plan', 'task'
    ));
