<?php

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

$active_id = (int) $argv[1];
$session = new ilTestSession($DIC->database(), $DIC->user());
$session->loadFromDb($active_id);
$db = $DIC->database();
$pass = $db->fetchAssoc($db->queryF(
    'SELECT points, finalized_by FROM tst_pass_result WHERE active_fi = %s AND pass = %s',
    ['integer', 'integer'], [$active_id, 0]
));
$question = $db->fetchAssoc($db->queryF(
    'SELECT points FROM tst_test_result WHERE active_fi = %s AND pass = %s',
    ['integer', 'integer'], [$active_id, 0]
));
$by_question = [];
$result = $db->queryF(
    'SELECT question_fi, points FROM tst_test_result WHERE active_fi = %s AND pass = %s',
    ['integer', 'integer'], [$active_id, 0]
);
while ($row = $db->fetchAssoc($result)) {
    $by_question[$row['question_fi']] = ['points' => (float) $row['points'], 'feedback' => null, 'final' => false];
}
$result = $db->queryF(
    'SELECT question_fi, feedback, finalized_evaluation FROM tst_manual_fb WHERE active_fi = %s AND pass = %s',
    ['integer', 'integer'], [$active_id, 0]
);
while ($row = $db->fetchAssoc($result)) {
    $by_question[$row['question_fi']]['feedback'] = $row['feedback'];
    $by_question[$row['question_fi']]['final'] = (bool) $row['finalized_evaluation'];
}
// Notifications are internal ILIAS mails in the participant's inbox, so nothing leaves the instance
$mails = [];
$result = $db->queryF(
    'SELECT m_subject FROM mail WHERE user_id = %s ORDER BY mail_id',
    ['integer'], [$session->getUserId()]
);
while ($row = $db->fetchAssoc($result)) {
    $mails[] = $row['m_subject'];
}
echo json_encode([
    'submitted' => $session->isSubmitted(),
    'last_finished_pass' => $session->getLastFinishedPass(),
    'finalized_by' => $pass['finalized_by'],
    'points' => (float) $pass['points'],
    'question_points' => (float) $question['points'],
    'grading_done' => ilTestService::isManScoringDone($active_id),
    'questions' => $by_question,
    'mails' => $mails,
], JSON_THROW_ON_ERROR) . "\n";
