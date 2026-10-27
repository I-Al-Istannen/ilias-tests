<?php

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

use ILIAS\Test\Settings\ScoreReporting\ScoreReportingTypes;

$test = new ilObjTest((int) $argv[1]);
$settings = $test->getScoreSettings();
if (($argv[2] ?? '') === 'reset') {
    $settings = $settings->withResultSummarySettings(
        $settings->getResultSummarySettings()
            ->withScoreReporting(ScoreReportingTypes::SCORE_REPORTING_DISABLED)
            ->withShowGradingStatusEnabled(false)
            ->withShowGradingMarkEnabled(false)
            ->withShowPassDetails(false)
    )->withResultDetailsSettings(
        $settings->getResultDetailsSettings()
            ->withShowPassDetails(false)
            ->withShowSolutionPrintview(false)
            ->withShowSolutionFeedback(false)
            ->withShowSolutionAnswersOnly(false)
            ->withShowSolutionSuggested(false)
            ->withShowSolutionListComparison(false)
    );
    $test->getScoreSettingsRepository()->store($settings);
}
$summary = $settings->getResultSummarySettings();
$details = $settings->getResultDetailsSettings();
echo json_encode([
    'reporting' => $summary->getScoreReporting()->value,
    'grade' => $summary->getShowGradingMarkEnabled(),
    'passed' => $summary->getShowGradingStatusEnabled(),
    'details' => $summary->getShowPassDetails(),
    'printview' => $details->getShowSolutionPrintview(),
    'feedback' => $details->getShowSolutionFeedback(),
    'hide_page_contents' => $details->getShowSolutionAnswersOnly(),
    'suggested_content' => $details->getShowSolutionSuggested(),
    'best_solution' => $details->getShowSolutionListComparison(),
], JSON_THROW_ON_ERROR) . "\n";
