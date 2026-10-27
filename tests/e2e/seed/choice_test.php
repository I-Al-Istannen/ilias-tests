<?php

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

// A test with choice questions, in its own folder so the other fixtures keep their question counts.
$folder = create_object('fold', 'Choices', (int) $argv[1]);
$test = create_object('tst', 'Choice Test', $folder->getRefId());
$test->saveToDb();

$single = new assSingleChoice('Pick one', 'A single choice', 'E2E Author', ROOT_USER_ID, '<p>Which answer is correct?</p>');
$single->feedbackOBJ = new ilAssSingleChoiceFeedback($single, $DIC->ctrl(), $DIC->database(), $DIC->language());
$single->setObjId($test->getId());
$single->setShuffle(false);
$single->addAnswer('Yes', 0.0, 0);
$single->addAnswer('No', 2.0, 1);
$single->saveToDb();
$test->insertQuestion($single->getId(), true);

$multiple = new assMultipleChoice('Pick several', 'A multiple choice', 'E2E Author', ROOT_USER_ID, '<p>Select the correct answers.</p>');
$multiple->feedbackOBJ = new ilAssMultipleChoiceFeedback($multiple, $DIC->ctrl(), $DIC->database(), $DIC->language());
$multiple->setObjId($test->getId());
$multiple->setShuffle(false);
$multiple->addAnswer('First', 1.0, 0.0, 0);
$multiple->addAnswer('Second', 1.0, 0.0, 1);
$multiple->addAnswer('Third', 0.0, 0.0, 2);
$multiple->saveToDb();
$test->insertQuestion($multiple->getId(), true);
$test->saveToDb();

echo json_encode([
    'test' => $test->getRefId(),
    'single' => $single->getId(),
    'multiple' => $multiple->getId(),
], JSON_THROW_ON_ERROR) . "\n";
