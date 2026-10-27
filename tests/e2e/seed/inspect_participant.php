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
echo json_encode([
    'submitted' => $session->isSubmitted(),
    'last_finished_pass' => $session->getLastFinishedPass(),
    'finalized_by' => $pass['finalized_by'],
    'points' => (float) $pass['points'],
    'question_points' => (float) $question['points'],
    'grading_done' => ilTestService::isManScoringDone($active_id),
], JSON_THROW_ON_ERROR) . "\n";
