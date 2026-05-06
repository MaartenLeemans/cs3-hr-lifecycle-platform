param(
    [string]$SamAccountName
)

Disable-ADAccount -Identity $SamAccountName

$Groups = Get-ADPrincipalGroupMembership $SamAccountName | Where-Object {$_.Name -ne "Domain Users"}

foreach ($Group in $Groups) {
    Remove-ADGroupMember -Identity $Group.Name -Members $SamAccountName -Confirm:$false
}

Move-ADObject `
-Identity (Get-ADUser $SamAccountName).DistinguishedName `
-TargetPath "OU=Disabled Users,OU=Innovatech,DC=innovatech,DC=local"

Write-Output "$SamAccountName successfully offboarded."