INSERT INTO `account`
    (`id`,`username`,`salt`,`verifier`,`session_key_auth`,`email`,`reg_mail`,
     `last_ip`,`last_attempt_ip`,`online`,`os`)
VALUES
    (1,'MIGRATION_TEST',UNHEX(REPEAT('11',32)),UNHEX(REPEAT('22',32)),
     UNHEX(REPEAT('33',40)),'test@example.invalid','test@example.invalid',
     '127.0.0.1','127.0.0.1',1,'Win'),
    (2,'MIGRATION_SIGNER',UNHEX(REPEAT('44',32)),UNHEX(REPEAT('55',32)),
     NULL,'signer@example.invalid','signer@example.invalid',
     '127.0.0.1','127.0.0.1',0,'Win');

INSERT INTO `account_access` (`AccountID`,`SecurityLevel`,`RealmID`,`Comment`)
VALUES (1,3,1,'migration fixture');

INSERT INTO `realmcharacters` (`realmid`,`acctid`,`numchars`)
VALUES (1,1,1);
