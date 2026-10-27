<?php

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

$objects = [];
foreach ($DIC->repositoryTree()->getChildsByType((int) $argv[1], 'tst') as $child) {
    $test = new ilObjTest((int) $child['ref_id']);
    $objects[] = [
        'title' => $test->getTitle(),
        'online' => !$test->getOfflineStatus(),
        'questions' => count($test->getQuestions()),
    ];
}
echo json_encode($objects, JSON_THROW_ON_ERROR) . "\n";
