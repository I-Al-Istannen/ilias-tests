<?php

/**
 * Bootstraps ILIAS as root and provides helpers to create the fixture objects.
 *
 * Uses the ILIAS object API directly, as the SOAP API is too limited (and addFile is broken for
 * inline content in ILIAS 10). Some objects need small fixups (mostly online flags and permissions)
 * that the GUI would normally do. These are noted where they happen.
 */

declare(strict_types=1);

chdir('/var/www/html');
require_once './vendor/composer/vendor/autoload.php';

// Not set in the CLI context, but needed e.g. by the news notifications of new files
define('ILIAS_HTTP_PATH', getenv('ILIAS_HTTP_PATH'));

const ROOT_REF_ID = 1;
const ROOT_USER_ID = 6;
const USER_ROLE_ID = 4;

(new ilCronStartUp('default', 'root'))->authenticate();

/**
 * Creates the object in the repository and makes it visible to the members of the surrounding course:
 * Most objects are offline by default and the default member role lacks permissions for some types.
 */
function put_in_tree(ilObject $obj, int $parent_ref_id): int
{
    global $DIC;

    $obj->create();
    $obj->createReference();
    $obj->putInTree($parent_ref_id);
    $obj->setPermissions($parent_ref_id);
    // ILIAS creates this entry on the first access. Parallel first accesses race, and the loser crashes
    // with "Undefined array key timing_type".
    ilObjectActivation::getItem($obj->getRefId());

    if ($DIC['objDefinition']->supportsOfflineHandling($obj->getType())) {
        $obj->setOfflineStatus(false);
        $obj->update();
    }

    if ($course_ref_id = $DIC->repositoryTree()->checkForParentType($obj->getRefId(), 'crs')) {
        $DIC->rbac()->admin()->grantPermission(
            (new ilObjCourse($course_ref_id))->getDefaultMemberRole(),
            ilRbacReview::_getOperationIdsByName(['visible', 'read']),
            $obj->getRefId()
        );
    }

    return $obj->getRefId();
}

function create_object(string $type, string $title, int $parent_ref_id): ilObject
{
    global $DIC;

    $class = 'ilObj' . $DIC['objDefinition']->getClassName($type);
    $obj = new $class();
    $obj->setTitle($title);
    put_in_tree($obj, $parent_ref_id);
    return $obj;
}

function create_user(string $login, string $password, string $language = 'en'): int
{
    global $DIC;

    $user = new ilObjUser();
    $user->setLogin($login);
    $user->setFirstname('Test');
    $user->setLastname(ucfirst($login));
    $user->setEmail("$login@example.com");
    $user->setPasswd($password, ilObjUser::PASSWD_PLAIN);
    $user->setActive(true);
    $user->setTimeLimitUnlimited(true);
    $user->setAgreeDate(date('Y-m-d H:i:s'));
    $user->setLanguage($language);
    $user->create();
    $user->saveAsNew();
    // saveAsNew does not store the preferences, which hold the language
    $user->writePrefs();
    // ILIAS creates this entry on the first login. Parallel first logins race, and the loser crashes
    // with "Duplicate entry".
    ilOnlineTracking::addUser($user->getId());

    $DIC->rbac()->admin()->assignUser(USER_ROLE_ID, $user->getId());
    return $user->getId();
}

function install_language(string $key): void
{
    (new ilObjLanguage((int) ilObject::_getIdsForTitle($key, 'lng')[0]))->install();
}

