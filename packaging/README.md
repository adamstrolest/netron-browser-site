# Netron Browser Packaging

This directory contains packaging files for non-Debian distributions.

## Arch Linux (AUR)

```bash
# Prerequisites (one-time):
# 1. Create an account at https://aur.archlinux.org/
# 2. Add your SSH public key in your AUR account settings

# Clone & publish:
git clone ssh://aur@aur.archlinux.org/netron-browser.git
cp packaging/arch/PKGBUILD netron-browser/
cd netron-browser
makepkg --printsrcinfo > .SRCINFO
git add -A && git commit -m "Initial AUR package"
git push origin master

# Users install with:
yay -S netron-browser
# or
paru -S netron-browser
```

## Fedora (COPR)

```bash
# Prerequisites (one-time):
# 1. Create an account at https://copr.fedorainfracloud.org/
# 2. Install copr-cli: dnf install copr-cli
# 3. Authenticate: copr-cli login

# Build SRPM:
spectool -g packaging/fedora/netron-browser.spec
rpmbuild -bs packaging/fedora/netron-browser.spec --define "_sourcedir $PWD" --define "_srcrpmdir $PWD"

# Create COPR project:
copr-cli create netron-browser --description "Netron Browser" --instructions "copr enable adam/netron-browser && dnf install netron-browser"

# Upload SRPM:
copr-cli build netron-browser netron-browser-1.7.0-1.src.rpm

# Users install with:
sudo dnf copr enable adam/netron-browser
sudo dnf install netron-browser
```
