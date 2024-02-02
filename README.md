# arch-ansible-simple-setup
A collection of Ansible playbooks for quick Arch Linux setup post-install. Demonstrates package installation from the mainstream Arch repos, AUR and Flatpak. Also demonstrates GNOME desktop settings changes.

## Important Notes
These playbooks were set up for my specific requirements. These requirements include use of the GNOME desktop, plus some locale packages for UK use. You will almost certainly want to modify these playbooks before using them!

However, they should be easy to understand and provide an excellent starting point for getting your Arch system exactly how you want it.

As it stands, these playbooks are only configured for use locally on the machine being set up.

As you know, Ansible playbooks are designed to be idempotent in use. This means you should be able to safely repeat any playbook as often as you choose, which will be useful as you modify it for your exact needs.

## Prerequisites
Arch must have been successfully installed along with a graphical desktop environment. `archinstall` is recommended. These playbooks should work equally well with distros based on Arch, and have been tested successfully with EndeavourOS.

The `ansible` package must be installed from the Arch repos. This could be added as an additional package when running `archinstall`, or installed later using `pacman`.

`git` must also be installed before this repo can be cloned (unless you prefer the option of downloading a ZIP file from GitHub).

Playbooks that work with the AUR have an additional prerequisite - please check the list below.

## Quick Start
1. Make sure you've read and understood everything above.
2. Clone or download the repo to your local PC.
3. Copy the file `etc/ansible/hosts` from your local repo to become `/etc/ansible/hosts` on the PC (requires `sudo` for root privileges).
4. Make sure you understand what is being changed by each playbook before running it, and modify to suit your needs.
5. Open a console/terminal in the root of your local repo.

You're now ready to run the playbooks. In each case, this is done using a command in the form of

`ansible-playbook -K <playbook_filename>`

The `-K` option leads to a prompt for the root password for package installation. 

## Playbooks
Select only the playbooks you need from this list. The first one is probably of most interest.

### `core.yml`
Installs a base set of packages from the mainstream Arch repos, inclusing Firefox, LibreOffice, GIMP, VLC and others.

Also removes some packages that are part of the default GNOME install, but which I will not be using.

### `aur.yml`
Installs packages from the Arch User Repository (AUR), including Chrome, VS Code and others.

This playbook has an additional prerequisite to allow Ansible to interact with the AUR. The `ansible-aur` collection should first be installed using:

`ansible-galaxy collection install kewlfft.aur`

### `flatpak.yml`
Installs a small number of Flatpaks.

### `games.yml`
Installs a couple of games from mainstream Arch repos.

### `dotnet.yml`
Installs packages for .NET development. Most likely you won't want these, but I need them for some of my development work.

### `gnome_conf.yml`
Makes some GNOME desktop config changes, including the addition of maximize and minimize buttons to window borders, and enabling permanent delete in Nautilus file manager.

### `kvm_qemu.yml`
Installs packages for virtualization support.

It's possible this playbook will initially fail because the default Arch install includes the `iptables` package rather than the newer `iptables-nft`. In this case you will need to replace one with the other before proceeding: -

`sudo pacman -S iptables-nft`

### `virtio-win.yml`
Installs virtualization drivers for Windows guest VMs from the AUR.