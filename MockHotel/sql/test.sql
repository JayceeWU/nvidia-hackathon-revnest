DELETE FROM room_type_price;
DELETE FROM room_type;
DELETE FROM account;

INSERT INTO account (id, username, password_hash, role) VALUES (
  '00000000-0000-0000-0000-000000000001',
  'manager',
  crypt('password123', gen_salt('bf')),
  'manager'
);
