-- The Offer agent asks the owner short questions ("Is the 15% on the whole bill?") through the inbox.
-- The answer is stored in inbox_items.decision.note and wakes the team.
alter table inbox_items drop constraint inbox_items_kind_check;
alter table inbox_items add constraint inbox_items_kind_check
  check (kind in ('approval', 'recommendation', 'finding', 'notice', 'question'));
