<?php

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

// Avoid the change-password screen after the first login.
$security = ilSecuritySettings::_getInstance();
$security->setPasswordChangeOnFirstLoginEnabled(false);
$security->save();
install_language('de');
// KIT enables the page editor for additional question content.
$DIC->settings()->set('enable_tst_page_edit', '1');

// The CLI requests German pages, so an English account checks that the account language does not matter.
$password = 'ilias-tests-e2e';
$teacher = create_user('teacher', $password, 'en');
$DIC->rbac()->admin()->assignUser(2, $teacher); // Administrator
$result = ['login' => 'teacher', 'password' => $password];
file_put_contents('/var/iliasdata/ilias/seed-result.json', json_encode($result, JSON_THROW_ON_ERROR));
echo json_encode($result, JSON_THROW_ON_ERROR) . "\n";
