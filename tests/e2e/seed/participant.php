<?php

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

use ILIAS\Test\Results\Data\Repository;
use ILIAS\Test\Results\Data\StatusOfAttempt;
use ILIAS\TestQuestionPool\QuestionPoolDIC;

$test = new ilObjTest((int) $argv[1]);
$login = 'student_' . bin2hex(random_bytes(6)) . '@example.com';
$user_id = create_user($login, 'ilias-tests-e2e', 'de');
$course_ref = $DIC->repositoryTree()->checkForParentType($test->getRefId(), 'crs');
(new ilObjCourse($course_ref))->getMembersObject()->add($user_id, ilParticipants::IL_CRS_MEMBER);
$user = new ilObjUser($user_id);
// KIT logins are email addresses, which the grading importer/exporter relies on.
$user->setEmail($login);
$user->update();
$session = new ilTestSession($DIC->database(), $user);
$session->setUserId($user_id);
$session->setTestId($test->getTestId());
$session->setRefId($test->getRefId());
$session->setLastStartedPass(0);
$session->saveToDb();
$active_id = $session->getActiveId();

$sequence = new ilTestSequenceFixedQuestionSet(
    $DIC->database(), $active_id, 0, QuestionPoolDIC::dic()['question.general_properties.repository']
);
$sequence->loadQuestions();
$sequence->createNewSequence(1, false);
$sequence->saveToDb();
$question_id = (int) array_values($test->getQuestions())[0];
$question = assQuestion::instantiateQuestion($question_id);
$question->saveCurrentSolution($active_id, 0, 'My independently seeded answer.', null);
assQuestion::_setReachedPoints($active_id, $question_id, 1.5, 4.0, 0, true);
$test->updateTestPassResults($active_id, 0);

if ($argv[2] === 'finished') {
    (new ilTestPassFinishTasks($session, $test, new Repository($DIC->database())))
        ->performFinishTasks(new ilTestProcessLockerNone(), StatusOfAttempt::FINISHED_BY_PARTICIPANT);
}

echo json_encode([
    'active_id' => $active_id,
    'question_id' => $question_id,
    'login' => $login,
    'email' => $user->getEmail(),
], JSON_THROW_ON_ERROR) . "\n";
