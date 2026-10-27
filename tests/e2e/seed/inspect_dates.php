<?php

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

// Times are reported in UTC, so the test can check how the CLI's local times were interpreted.
function utc(?DateTimeImmutable $time): ?string
{
    return $time?->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d H:i');
}

$objects = [];
foreach ($DIC->repositoryTree()->getChildsByType((int) $argv[1], 'tst') as $child) {
    $test = new ilObjTest((int) $child['ref_id']);
    $access = $test->getMainSettings()->getAccessSettings();
    $activation = ilObjectActivation::getItem($test->getRefId());
    $objects[] = [
        'title' => $test->getTitle(),
        'online' => !$test->getOfflineStatus(),
        'start_enabled' => $access->getStartTimeEnabled(),
        'start' => utc($access->getStartTime()),
        'end_enabled' => $access->getEndTimeEnabled(),
        'end' => utc($access->getEndTime()),
        // The object's availability period, which is separate from the test's access times
        'availability' => (int) $activation['timing_type'] === ilObjectActivation::TIMINGS_ACTIVATION,
    ];
}
echo json_encode($objects, JSON_THROW_ON_ERROR) . "\n";
