<?php

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

// Each test gets its own tree, including when a kept stack is reused or xdist is used.
$course = create_object('crs', 'E2E ' . $argv[1], ROOT_REF_ID);
$source = create_object('fold', 'Source', $course->getRefId());
$target = create_object('fold', 'Target', $course->getRefId());
$other = create_object('fold', 'Other', $course->getRefId());

$test = create_object('tst', 'Seeded Test', $source->getRefId());
$test->setDescription('A fixture created independently of the CLI');
$test->update();
$test->saveToDb();
$question = new assTextQuestion('Explain', 'A short explanation', 'E2E Author', ROOT_USER_ID, '<p>Explain your answer.</p>');
$question->feedbackOBJ = new ilAssTextQuestionFeedback($question, $DIC->ctrl(), $DIC->database(), $DIC->language());
$question->setObjId($test->getId());
$question->setPoints(4.0);
$question->saveToDb();
$test->insertQuestion($question->getId(), true);
$test->saveToDb();

echo json_encode([
    'course' => $course->getRefId(),
    'source' => $source->getRefId(),
    'target' => $target->getRefId(),
    'other' => $other->getRefId(),
    'test' => $test->getRefId(),
], JSON_THROW_ON_ERROR) . "\n";
