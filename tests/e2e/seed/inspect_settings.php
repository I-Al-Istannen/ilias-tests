<?php

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

// Reports the settings `configure` writes, read through the ILIAS settings API.
function utc(?DateTimeImmutable $time): ?string
{
    return $time?->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d H:i');
}

$test = new ilObjTest((int) $argv[1]);
$settings = $test->getMainSettings();
$general = $settings->getGeneralSettings();
$intro = $settings->getIntroductionSettings();
$access = $settings->getAccessSettings();
$behaviour = $settings->getTestBehaviourSettings();
$question = $settings->getQuestionBehaviourSettings();
$participant = $settings->getParticipantFunctionalitySettings();
$finishing = $settings->getFinishingSettings();
$activation = ilObjectActivation::getItem($test->getRefId());
$intro_page = $intro->getIntroductionPageId();

echo json_encode([
    'title' => $test->getTitle(),
    'description' => $test->getDescription(),
    'online' => !$test->getOfflineStatus(),
    'availability' => (int) $activation['timing_type'] === ilObjectActivation::TIMINGS_ACTIVATION,
    'question_set_type' => $general->getQuestionSetType(),
    'anonymity' => $general->getAnonymity(),
    'intro_enabled' => $intro->getIntroductionEnabled(),
    'intro_text' => $intro_page === null ? null : trim(preg_replace(
        '/\s+/',
        ' ',
        strip_tags(str_replace('<', ' <', (new ilTestPage($intro_page))->getXMLContent()))
    )),
    'start' => $access->getStartTimeEnabled() ? utc($access->getStartTime()) : null,
    'end' => $access->getEndTimeEnabled() ? utc($access->getEndTime()) : null,
    'number_of_tries' => $behaviour->getNumberOfTries(),
    'title_output' => $question->getQuestionTitleOutputMode(),
    'lock_answer_on_feedback' => $question->getLockAnswerOnInstantFeedbackEnabled(),
    'lock_answer_on_next' => $question->getLockAnswerOnNextQuestionEnabled(),
    'autosave' => $question->getAutosaveEnabled(),
    'use_previous_answers' => $participant->getUsePreviousAnswerAllowed(),
    'suspend' => $participant->getSuspendTestAllowed(),
    'postponed_to_end' => $participant->getPostponedQuestionsMoveToEnd(),
    'question_list' => $participant->getQuestionListEnabled(),
    'pass_overview' => $participant->getUsrPassOverviewEnabled(),
    'pass_overview_at_end' => $participant->getShownQuestionListAtEnd(),
    'pass_overview_descriptions' => $participant->getShowDescriptionInQuestionList(),
    'question_marking' => $participant->getQuestionMarkingEnabled(),
    'answer_overview' => $finishing->getShowAnswerOverview(),
], JSON_THROW_ON_ERROR) . "\n";
