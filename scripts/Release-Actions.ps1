[CmdletBinding()]
param([Parameter(Mandatory)][ValidateSet('Prepare', 'Upload', 'Finalize')][string]$Phase)
$ErrorActionPreference = 'Stop'
$tag = $env:RELEASE_TAG
$repo = $env:GITHUB_REPOSITORY
$automaticTag = $Phase -eq 'Prepare' -and [string]::IsNullOrWhiteSpace($tag)
if ($automaticTag) {
    $versionFile = Join-Path (Split-Path $PSScriptRoot -Parent) 'version.h.in'
    $version = [regex]::Match((Get-Content -LiteralPath $versionFile -Raw), '(?m)^#define VERSION "([^"]+)"')
    if (-not $version.Success) { throw 'VERSION missing from version.h.in' }
    $tag = 'v' + $version.Groups[1].Value
}
if ($tag -cnotmatch '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') { throw 'Expected vMAJOR.MINOR.PATCH' }
if (-not $repo) { throw 'GITHUB_REPOSITORY is required' }
# All jobs use Prepare's resolved tag/SHA. Blank input tags the selected run commit;
# an existing automatic tag must match it. Uploads are individually retryable; a failed
# matrix leaves a draft. Never overwrite an already published release (docs/RELEASE.md).
function Read-GhJson([string[]]$Arguments) {
    $json = & gh @Arguments
    if ($LASTEXITCODE -ne 0) { throw "GitHub read failed: $($Arguments[0])" }
    return ($json -join "`n" | ConvertFrom-Json)
}
function Get-TagCommit {
    $ref = Read-GhJson @('api', "repos/$repo/git/ref/tags/$tag")
    $object = $ref.object
    while ($object.type -eq 'tag') {
        $annotated = Read-GhJson @('api', "repos/$repo/git/tags/$($object.sha)")
        $object = $annotated.object
    }
    if ($object.type -ne 'commit') { throw 'Tag must resolve to a commit' }
    return $object.sha
}
function Get-CheckedDraft([string]$Sha) {
    $release = Read-GhJson @('release', 'view', $tag, '--repo', $repo, '--json', 'isDraft,body,assets')
    if (-not $release.isDraft) { throw 'Published releases cannot be modified by this workflow' }
    if (-not $release.body.Contains("Source commit: $Sha")) { throw 'Draft source does not match this build' }
    return $release
}
if ($Phase -eq 'Prepare') {
    $platforms = switch ($env:RELEASE_PLATFORM) {
        'all' { @('windows', 'linux') }
        'windows' { @('windows') }
        'linux' { @('linux') }
        default { throw 'Select all, windows or linux' }
    }
    if ($automaticTag) {
        $sha = git rev-parse --verify HEAD
        if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve selected run commit' }
        $remoteRef = git ls-remote origin "refs/tags/$tag"
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect remote tag' }
        if ($remoteRef -and (Get-TagCommit) -ne $sha) { throw 'Version tag already points to different code; bump VERSION or specify an existing tag' }
    } else {
        $sha = Get-TagCommit
        $localSha = git rev-parse --verify "refs/tags/$tag`^{commit}"
        if ($LASTEXITCODE -ne 0 -or $localSha -ne $sha) { throw 'Local and remote tag differ' }
    }
    foreach ($path in @('.github/actions/native-build/action.yml', 'scripts/Build-Actions.ps1', 'scripts/Package-Actions.ps1', 'scripts/Release-Actions.ps1')) {
        git cat-file -e "${sha}:$path"
        if ($LASTEXITCODE -ne 0) { throw "Tag lacks release infrastructure: $path" }
    }
    if ($automaticTag -and -not $remoteRef) {
        gh api "repos/$repo/git/refs" --method POST -f "ref=refs/tags/$tag" -f "sha=$sha"
        if ($LASTEXITCODE -ne 0) { throw 'Version tag creation failed; no existing tag is overwritten' }
        if ((Get-TagCommit) -ne $sha) { throw 'Created tag does not match selected run commit' }
    }
    $releases = @(Read-GhJson @('release', 'list', '--repo', $repo, '--limit', '1000', '--json', 'tagName'))
    if ($releases | Where-Object { $_.tagName -ceq $tag }) {
        $null = Get-CheckedDraft $sha
    } else {
        $notes = Join-Path $env:RUNNER_TEMP 'release-notes.md'
        "Source commit: $sha`n`nBuilt on GitHub-hosted runners. Assets may be incomplete until all selected jobs succeed." | Set-Content -LiteralPath $notes
        gh release create $tag --repo $repo --verify-tag --draft --title $tag --generate-notes --notes-file $notes
        if ($LASTEXITCODE -ne 0) { throw 'Draft creation failed' }
    }
    $include = @($platforms | ForEach-Object { @{platform=$_;os=$(if ($_ -eq 'windows') {'windows-2022'} else {'ubuntu-24.04'})} })
    "tag=$tag" >> $env:GITHUB_OUTPUT
    "sha=$sha" >> $env:GITHUB_OUTPUT
    "matrix=$(@{include=$include} | ConvertTo-Json -Depth 4 -Compress)" >> $env:GITHUB_OUTPUT
    exit 0
}
$sha = Get-TagCommit
if ($sha -ne $env:RELEASE_SHA) { throw 'Tag moved after build preparation' }
$release = Get-CheckedDraft $sha
if ($Phase -eq 'Upload') {
    $assets = @(Get-ChildItem -LiteralPath (Join-Path (Split-Path $PSScriptRoot -Parent) 'out/release') -File)
    if ($assets.Count -eq 0 -or @($assets | Where-Object Length -eq 0).Count) { throw 'Missing or empty release assets' }
    gh release upload $tag --repo $repo --clobber @($assets.FullName)
    if ($LASTEXITCODE -ne 0) { throw 'Asset upload failed; draft may contain partial assets' }
    exit 0
}
$expected = @()
if ($env:RELEASE_PLATFORM -in @('all', 'windows')) { $expected += "ScanTailor-$tag-windows-x64.zip", 'SHA256SUMS-windows.txt' }
if ($env:RELEASE_PLATFORM -in @('all', 'linux')) { $expected += "ScanTailor-$tag-linux-x64.deb", "ScanTailor-$tag-linux-x64.AppImage", 'SHA256SUMS-linux.txt' }
if ($expected.Count -eq 0) { throw 'Invalid platform selection' }
foreach ($name in $expected) {
    if (-not ($release.assets | Where-Object { $_.name -ceq $name -and $_.size -gt 0 })) { throw "Missing release asset: $name" }
}
if ($env:KEEP_DRAFT -eq 'false') {
    gh release edit $tag --repo $repo --draft=false
    if ($LASTEXITCODE -ne 0) { throw 'Release publication failed' }
} elseif ($env:KEEP_DRAFT -ne 'true') { throw 'KEEP_DRAFT must be true or false' }
"Release ready: https://github.com/$repo/releases (tag $tag)" >> $env:GITHUB_STEP_SUMMARY
