import os
import tomllib
from typing import Any


def main():
    with open("./config.toml", "rb") as f:
        config = tomllib.load(f)
        process(config)


def process(config: dict[str, Any]):
    check_config(config)
    enable_ntp()
    setup_network(config)
    format_partition(config)
    mount_partition(config)
    setup_system(config)
    umount()
    pass


def check_config(config: dict[str, Any]):
    if config["user"]["shell"] not in config["os"]["packages"]:
        print("[CONFIG_ERROR] user.shell is not included in os.packages.")
        exit(0)
    if (
        not config["grub"]["disable_os_prober"]
        and "os-prober" not in config["os"]["packages"]
    ):
        print(
            "[CONFIG_ERROR] grub.disable_os_prober is false, but os-prober is not included in os.packages."
        )
        exit(0)


def enable_ntp():
    os.system("timedatectl set-ntp true")


def setup_network(config: dict[str, Any]):
    # 如果 reflector 配置为 true，则使用 reflector 命令获取镜像源
    if config["network"]["reflector"]:
        os.system("reflector -c China -l 10 --sort rate --save /etc/pacman.d/mirrorlist")
    else:
        os.system("systemctl stop reflector.service")

    # 如果配置中提供了自定义的镜像源，则写入它们
    mirrors: list[str] = [
        f"Server = {mirror}" for mirror in config["network"]["mirrors"]
    ]
    
    # 如果自定义镜像列表不为空，写入镜像列表
    if len(mirrors) != 0:
        write_file("/etc/pacman.d/mirrorlist", multiline_str(*mirrors))




def format_partition(config: dict[str, Any]):
    boot = config["partition"]["boot"]
    root = config["partition"]["root"]
    label = config["partition"]["label"]
    os.system(f"mkfs.fat -F32 {boot}")
    os.system(f"mkfs.btrfs -fL {label} {root}")
    os.system(f"mount -t btrfs -o compress=zstd {root} /mnt")
    os.system("btrfs subvolume create /mnt/@")
    os.system("btrfs subvolume create /mnt/@home")
    os.system("btrfs subvolume create /mnt/@var-tmp")
    os.system("btrfs subvolume create /mnt/@var-cache")
    os.system("umount /mnt")


def mount_partition(config: dict[str, Any]):
    boot = config["partition"]["boot"]
    root = config["partition"]["root"]
    os.system(f"mount -t btrfs -o subvol=/@,compress=zstd {root} /mnt")
    os.system("mkdir -p /mnt/home")
    os.system(f"mount -t btrfs -o subvol=/@home,compress=zstd {root} /mnt/home")
    os.system("mkdir -p /mnt/var/tmp")
    os.system(f"mount -t btrfs -o subvol=/@var-tmp,compress=zstd {root} /mnt/var/tmp")
    os.system("mkdir -p /mnt/var/cache")
    os.system(f"mount -t btrfs -o subvol=/@var-cache,compress=zstd,nodatacow {root} /mnt/var/cache")
    os.system("mkdir -p /mnt/boot")
    os.system(f"mount {boot} /mnt/boot")


def setup_system(config: dict[str, Any]):
    update_keyring(config)
    setup_packages(config)
    gen_fstab()
    setup_grub(config)
    setup_timezone(config)
    setup_locale(config)
    setup_hosts(config)
    setup_pacman(config)
    setup_network(config)
    setup_root()
    setup_user(config)
    enable_services(config)

def update_keyring(config: dict[str, Any]):
    # 安装 haveged 以加速密钥环的生成
    os.system("pacman -Syu haveged --noconfirm")
    os.system("systemctl start haveged")
    os.system("systemctl enable haveged")
    
    # 删除现有的 gnupg 目录
    os.system("rm -fr /etc/pacman.d/gnupg")
    
    # 初始化并更新密钥环
    os.system("pacman-key --init")
    os.system("pacman-key --populate archlinux")
    
    # 如果启用了 archlinuxcn 仓库，也需要更新其密钥
    if config["pacman"]["archlinuxcn"]:
        os.system("pacman-key --populate archlinuxcn")

def setup_packages(config: dict[str, Any]):
    packages_: list[str] = config["os"]["packages"]
    packages = " ".join(packages_)
    os.system(f"pacstrap /mnt {packages}")


def setup_grub(config: dict[str, Any]):
    bootloader_id = config["grub"]["bootloader_id"]
    os.system(
        f"arch-chroot /mnt grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id={bootloader_id}"
    )
    if not config["grub"]["disable_os_prober"]:
        append_file("/mnt/etc/default/grub", "GRUB_DISABLE_OS_PROBER=false")
    os.system("arch-chroot /mnt grub-mkconfig -o /boot/grub/grub.cfg")


def gen_fstab():
    os.system("genfstab -U /mnt > /mnt/etc/fstab")


def setup_timezone(config: dict[str, Any]):
    timezone = config["os"]["timezone"]
    os.system(f"arch-chroot /mnt ln -sf /usr/share/zoneinfo/{timezone} /etc/localtime")
    os.system("arch-chroot /mnt hwclock --systohc")


def setup_locale(config: dict[str, Any]):
    lang = config["os"]["lang"]
    locale = multiline_str(*config["os"]["locale"])
    append_file("/mnt/etc/locale.gen", locale)
    os.system("arch-chroot /mnt locale-gen")
    write_file("/mnt/etc/locale.conf", f"LANG={lang}")


def setup_root(config: dict[str, Any]):
    # 获取配置文件中的 root 密码
    root_password = config.get("user", {}).get("root_password", "")

    if root_password:
        # 如果配置了 root 密码，直接通过 echo 自动设置密码
        print("Setting root password automatically...")
        os.system(f"echo root:{root_password} | arch-chroot /mnt chpasswd")
    else:
        # 如果没有配置 root 密码，提示用户手动输入密码
        print("Password for root: ")
        os.system("arch-chroot /mnt passwd root")  # 手动输入密码，使用 `passwd` 命令



def setup_user(config: dict[str, Any]):
    username = config["user"]["name"]
    shell = config["user"]["shell"]
    os.system(f"arch-chroot /mnt useradd -m -G wheel -s /usr/bin/{shell} {username}")
    print(f"password for {username}: ")
    os.system(f"arch-chroot /mnt passwd {username}")
    append_file("/mnt/etc/sudoers", "%wheel ALL=(ALL:ALL) ALL")


def setup_hosts(config: dict[str, Any]):
    hostname = config["os"]["hostname"]
    os.system(f"echo {hostname} > /mnt/etc/hostname")
    content = multiline_str(
        "127.0.0.1 localhost",
        "::1       localhost",
        f"127.0.1.1 {hostname}.localdomain {hostname}",
    )
    with open("/mnt/etc/hosts", "w") as f:
        f.write(content)


def setup_pacman(config: dict[str, Any]):
    if config["pacman"]["multilib"]:
        enable_multilib()
    if config["pacman"]["archlinuxcn"]:
        enable_archlinuxcn()


def enable_multilib():
    content = multiline_str("[multilib]", "Include = /etc/pacman.d/mirrorlist")
    append_file("/mnt/etc/pacman.conf", content)


def enable_archlinuxcn():
    content = multiline_str(
        "[archlinuxcn]", "Server = https://repo.archlinuxcn.org/$arch"
    )
    append_file("/mnt/etc/pacman.conf", content)


def enable_services(config: dict[str, Any]):
    for service in config["os"]["enabled_services"]:
        os.system(f"arch-chroot /mnt systemctl enable {service}")


def umount():
    os.system("umount -R /mnt")


# tool functions


def multiline_str(*s: str) -> str:
    return "\n".join(s) + "\n"


def write_file(filename, content):
    with open(filename, "w") as f:
        f.write(content)


def append_file(filename, content):
    with open(filename, "a") as f:
        f.write(content)


if __name__ == "__main__":
    main()