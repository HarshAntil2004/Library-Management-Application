-- 002: branches, tiers and public holidays (the closed days used by fines).

INSERT INTO branches (id, name, area) VALUES
 (1, 'Hazratganj Central Library', 'Hazratganj'),
 (2, 'Aminabad Community Library', 'Aminabad'),
 (3, 'Gomti Nagar Branch Library', 'Gomti Nagar');

-- policy numbers: rate is paise per day, cap is paise.
INSERT INTO membership_tiers
 (id, name, max_loans, loan_days, max_renewals, annual_fee_paise,
  fine_policy, fine_rate_paise, grace_days, fine_cap_paise) VALUES
 (1, 'Basic',    3, 14, 1,  20000, 'escalating', 200, 2, 20000),
 (2, 'Standard', 5, 21, 2,  50000, 'flat',       200, 3, 20000),
 (3, 'Premium', 10, 28, 3, 100000, 'flat',       150, 5, 10000);

-- Dates are approximate (lunar festivals shift); good enough for a fictional network.
INSERT INTO holidays (day, name) VALUES
 ('2025-11-05', 'Guru Nanak Jayanti'),
 ('2025-12-25', 'Christmas'),
 ('2026-01-26', 'Republic Day'),
 ('2026-03-04', 'Holi'),
 ('2026-03-21', 'Eid ul-Fitr'),
 ('2026-04-14', 'Ambedkar Jayanti'),
 ('2026-08-15', 'Independence Day'),
 ('2026-10-02', 'Gandhi Jayanti'),
 ('2026-10-20', 'Dussehra'),
 ('2026-11-08', 'Diwali');
