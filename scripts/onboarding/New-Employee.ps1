param(
    [string]$Name,
    [string]$Email,
    [string]$Department,
    [string]$Role
)

$SamAccountName = $Email.Split("@")[0]

$OU = "OU=Employees,OU=Innovatech,DC=innovatech,DC=local"

$Password = ConvertTo-SecureString "Welcome123!" -AsPlainText -Force

New-ADUser `
    -Name $Name `
    -SamAccountName $SamAccountName `
    -UserPrincipalName $Email `
    -Department $Department `
    -Title $Role `
    -AccountPassword $Password `
    -Enabled $true `
    -Path $OU

Add-ADGroupMember -Identity "GG_$Department" -Members $SamAccountName

Write-Output "User $Name successfully onboarded."