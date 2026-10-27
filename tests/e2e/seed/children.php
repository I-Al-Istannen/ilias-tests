<?php

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

echo json_encode(array_map(
    fn(array $child): int => (int) $child['ref_id'],
    array_values($DIC->repositoryTree()->getChildsByType((int) $argv[1], 'tst'))
), JSON_THROW_ON_ERROR) . "\n";
