/*
 Navicat Premium Data Transfer

 Source Server         : localhost
 Source Server Type    : MySQL
 Source Server Version : 80030
 Source Host           : localhost:3306
 Source Schema         : hoimsystem

 Target Server Type    : MySQL
 Target Server Version : 80030
 File Encoding         : 65001

 Date: 19/12/2022 19:33:20
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for auth_group
-- ----------------------------
DROP TABLE IF EXISTS `auth_group`;
CREATE TABLE `auth_group`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `name` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `name`(`name`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of auth_group
-- ----------------------------

-- ----------------------------
-- Table structure for auth_group_permissions
-- ----------------------------
DROP TABLE IF EXISTS `auth_group_permissions`;
CREATE TABLE `auth_group_permissions`  (
  `id` bigint(0) NOT NULL AUTO_INCREMENT,
  `group_id` int(0) NOT NULL,
  `permission_id` int(0) NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `auth_group_permissions_group_id_permission_id_0cd325b0_uniq`(`group_id`, `permission_id`) USING BTREE,
  INDEX `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm`(`permission_id`) USING BTREE,
  CONSTRAINT `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of auth_group_permissions
-- ----------------------------

-- ----------------------------
-- Table structure for auth_permission
-- ----------------------------
DROP TABLE IF EXISTS `auth_permission`;
CREATE TABLE `auth_permission`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `content_type_id` int(0) NOT NULL,
  `codename` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `auth_permission_content_type_id_codename_01ab375a_uniq`(`content_type_id`, `codename`) USING BTREE,
  CONSTRAINT `auth_permission_content_type_id_2f476e4b_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 88 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of auth_permission
-- ----------------------------
INSERT INTO `auth_permission` VALUES (1, 'Can add log entry', 1, 'add_logentry');
INSERT INTO `auth_permission` VALUES (2, 'Can change log entry', 1, 'change_logentry');
INSERT INTO `auth_permission` VALUES (3, 'Can delete log entry', 1, 'delete_logentry');
INSERT INTO `auth_permission` VALUES (4, 'Can view log entry', 1, 'view_logentry');
INSERT INTO `auth_permission` VALUES (5, 'Can add permission', 2, 'add_permission');
INSERT INTO `auth_permission` VALUES (6, 'Can change permission', 2, 'change_permission');
INSERT INTO `auth_permission` VALUES (7, 'Can delete permission', 2, 'delete_permission');
INSERT INTO `auth_permission` VALUES (8, 'Can view permission', 2, 'view_permission');
INSERT INTO `auth_permission` VALUES (9, 'Can add group', 3, 'add_group');
INSERT INTO `auth_permission` VALUES (10, 'Can change group', 3, 'change_group');
INSERT INTO `auth_permission` VALUES (11, 'Can delete group', 3, 'delete_group');
INSERT INTO `auth_permission` VALUES (12, 'Can view group', 3, 'view_group');
INSERT INTO `auth_permission` VALUES (13, 'Can add user', 4, 'add_user');
INSERT INTO `auth_permission` VALUES (14, 'Can change user', 4, 'change_user');
INSERT INTO `auth_permission` VALUES (15, 'Can delete user', 4, 'delete_user');
INSERT INTO `auth_permission` VALUES (16, 'Can view user', 4, 'view_user');
INSERT INTO `auth_permission` VALUES (17, 'Can add content type', 5, 'add_contenttype');
INSERT INTO `auth_permission` VALUES (18, 'Can change content type', 5, 'change_contenttype');
INSERT INTO `auth_permission` VALUES (19, 'Can delete content type', 5, 'delete_contenttype');
INSERT INTO `auth_permission` VALUES (20, 'Can view content type', 5, 'view_contenttype');
INSERT INTO `auth_permission` VALUES (21, 'Can add session', 6, 'add_session');
INSERT INTO `auth_permission` VALUES (22, 'Can change session', 6, 'change_session');
INSERT INTO `auth_permission` VALUES (23, 'Can delete session', 6, 'delete_session');
INSERT INTO `auth_permission` VALUES (24, 'Can view session', 6, 'view_session');
INSERT INTO `auth_permission` VALUES (25, 'Can add department', 7, 'add_department');
INSERT INTO `auth_permission` VALUES (26, 'Can change department', 7, 'change_department');
INSERT INTO `auth_permission` VALUES (27, 'Can delete department', 7, 'delete_department');
INSERT INTO `auth_permission` VALUES (28, 'Can view department', 7, 'view_department');
INSERT INTO `auth_permission` VALUES (29, 'Can add doctor', 8, 'add_doctor');
INSERT INTO `auth_permission` VALUES (30, 'Can change doctor', 8, 'change_doctor');
INSERT INTO `auth_permission` VALUES (31, 'Can delete doctor', 8, 'delete_doctor');
INSERT INTO `auth_permission` VALUES (32, 'Can view doctor', 8, 'view_doctor');
INSERT INTO `auth_permission` VALUES (33, 'Can add patient', 9, 'add_patient');
INSERT INTO `auth_permission` VALUES (34, 'Can change patient', 9, 'change_patient');
INSERT INTO `auth_permission` VALUES (35, 'Can delete patient', 9, 'delete_patient');
INSERT INTO `auth_permission` VALUES (36, 'Can view patient', 9, 'view_patient');
INSERT INTO `auth_permission` VALUES (37, 'Can add pharmaceutical', 10, 'add_pharmaceutical');
INSERT INTO `auth_permission` VALUES (38, 'Can change pharmaceutical', 10, 'change_pharmaceutical');
INSERT INTO `auth_permission` VALUES (39, 'Can delete pharmaceutical', 10, 'delete_pharmaceutical');
INSERT INTO `auth_permission` VALUES (40, 'Can view pharmaceutical', 10, 'view_pharmaceutical');
INSERT INTO `auth_permission` VALUES (41, 'Can add reg_category', 11, 'add_reg_category');
INSERT INTO `auth_permission` VALUES (42, 'Can change reg_category', 11, 'change_reg_category');
INSERT INTO `auth_permission` VALUES (43, 'Can delete reg_category', 11, 'delete_reg_category');
INSERT INTO `auth_permission` VALUES (44, 'Can view reg_category', 11, 'view_reg_category');
INSERT INTO `auth_permission` VALUES (45, 'Can add timeslot', 12, 'add_timeslot');
INSERT INTO `auth_permission` VALUES (46, 'Can change timeslot', 12, 'change_timeslot');
INSERT INTO `auth_permission` VALUES (47, 'Can delete timeslot', 12, 'delete_timeslot');
INSERT INTO `auth_permission` VALUES (48, 'Can view timeslot', 12, 'view_timeslot');
INSERT INTO `auth_permission` VALUES (49, 'Can add users', 13, 'add_users');
INSERT INTO `auth_permission` VALUES (50, 'Can change users', 13, 'change_users');
INSERT INTO `auth_permission` VALUES (51, 'Can delete users', 13, 'delete_users');
INSERT INTO `auth_permission` VALUES (52, 'Can view users', 13, 'view_users');
INSERT INTO `auth_permission` VALUES (53, 'Can add registration', 14, 'add_registration');
INSERT INTO `auth_permission` VALUES (54, 'Can change registration', 14, 'change_registration');
INSERT INTO `auth_permission` VALUES (55, 'Can delete registration', 14, 'delete_registration');
INSERT INTO `auth_permission` VALUES (56, 'Can view registration', 14, 'view_registration');
INSERT INTO `auth_permission` VALUES (57, 'Can add prescription', 15, 'add_prescription');
INSERT INTO `auth_permission` VALUES (58, 'Can change prescription', 15, 'change_prescription');
INSERT INTO `auth_permission` VALUES (59, 'Can delete prescription', 15, 'delete_prescription');
INSERT INTO `auth_permission` VALUES (60, 'Can view prescription', 15, 'view_prescription');
INSERT INTO `auth_permission` VALUES (61, 'Can add pre_pha', 16, 'add_pre_pha');
INSERT INTO `auth_permission` VALUES (62, 'Can change pre_pha', 16, 'change_pre_pha');
INSERT INTO `auth_permission` VALUES (63, 'Can delete pre_pha', 16, 'delete_pre_pha');
INSERT INTO `auth_permission` VALUES (64, 'Can view pre_pha', 16, 'view_pre_pha');
INSERT INTO `auth_permission` VALUES (65, 'Can add notice', 17, 'add_notice');
INSERT INTO `auth_permission` VALUES (66, 'Can change notice', 17, 'change_notice');
INSERT INTO `auth_permission` VALUES (67, 'Can delete notice', 17, 'delete_notice');
INSERT INTO `auth_permission` VALUES (68, 'Can view notice', 17, 'view_notice');
INSERT INTO `auth_permission` VALUES (69, 'Can add medical_record', 18, 'add_medical_record');
INSERT INTO `auth_permission` VALUES (70, 'Can change medical_record', 18, 'change_medical_record');
INSERT INTO `auth_permission` VALUES (71, 'Can delete medical_record', 18, 'delete_medical_record');
INSERT INTO `auth_permission` VALUES (72, 'Can view medical_record', 18, 'view_medical_record');
INSERT INTO `auth_permission` VALUES (73, 'Can add doctor_schedule', 19, 'add_doctor_schedule');
INSERT INTO `auth_permission` VALUES (74, 'Can change doctor_schedule', 19, 'change_doctor_schedule');
INSERT INTO `auth_permission` VALUES (75, 'Can delete doctor_schedule', 19, 'delete_doctor_schedule');
INSERT INTO `auth_permission` VALUES (76, 'Can view doctor_schedule', 19, 'view_doctor_schedule');
INSERT INTO `auth_permission` VALUES (77, 'Can add breach_record', 20, 'add_breach_record');
INSERT INTO `auth_permission` VALUES (78, 'Can change breach_record', 20, 'change_breach_record');
INSERT INTO `auth_permission` VALUES (79, 'Can delete breach_record', 20, 'delete_breach_record');
INSERT INTO `auth_permission` VALUES (80, 'Can view breach_record', 20, 'view_breach_record');
INSERT INTO `auth_permission` VALUES (81, 'Can add appointment', 21, 'add_appointment');
INSERT INTO `auth_permission` VALUES (82, 'Can change appointment', 21, 'change_appointment');
INSERT INTO `auth_permission` VALUES (83, 'Can delete appointment', 21, 'delete_appointment');
INSERT INTO `auth_permission` VALUES (84, 'Can view appointment', 21, 'view_appointment');
INSERT INTO `auth_permission` VALUES (85, 'Can add charge', 22, 'add_charge');
INSERT INTO `auth_permission` VALUES (86, 'Can change charge', 22, 'change_charge');
INSERT INTO `auth_permission` VALUES (87, 'Can delete charge', 22, 'delete_charge');
INSERT INTO `auth_permission` VALUES (88, 'Can view charge', 22, 'view_charge');

-- ----------------------------
-- Table structure for auth_user
-- ----------------------------
DROP TABLE IF EXISTS `auth_user`;
CREATE TABLE `auth_user`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `password` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `last_login` datetime(6) NULL DEFAULT NULL,
  `is_superuser` tinyint(1) NOT NULL,
  `username` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `first_name` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `last_name` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `email` varchar(254) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `is_staff` tinyint(1) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `date_joined` datetime(6) NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `username`(`username`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of auth_user
-- ----------------------------

-- ----------------------------
-- Table structure for auth_user_groups
-- ----------------------------
DROP TABLE IF EXISTS `auth_user_groups`;
CREATE TABLE `auth_user_groups`  (
  `id` bigint(0) NOT NULL AUTO_INCREMENT,
  `user_id` int(0) NOT NULL,
  `group_id` int(0) NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `auth_user_groups_user_id_group_id_94350c0c_uniq`(`user_id`, `group_id`) USING BTREE,
  INDEX `auth_user_groups_group_id_97559544_fk_auth_group_id`(`group_id`) USING BTREE,
  CONSTRAINT `auth_user_groups_group_id_97559544_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `auth_user_groups_user_id_6a12ed8b_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of auth_user_groups
-- ----------------------------

-- ----------------------------
-- Table structure for auth_user_user_permissions
-- ----------------------------
DROP TABLE IF EXISTS `auth_user_user_permissions`;
CREATE TABLE `auth_user_user_permissions`  (
  `id` bigint(0) NOT NULL AUTO_INCREMENT,
  `user_id` int(0) NOT NULL,
  `permission_id` int(0) NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `auth_user_user_permissions_user_id_permission_id_14a6b632_uniq`(`user_id`, `permission_id`) USING BTREE,
  INDEX `auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm`(`permission_id`) USING BTREE,
  CONSTRAINT `auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of auth_user_user_permissions
-- ----------------------------

-- ----------------------------
-- Table structure for django_admin_log
-- ----------------------------
DROP TABLE IF EXISTS `django_admin_log`;
CREATE TABLE `django_admin_log`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `action_time` datetime(6) NOT NULL,
  `object_id` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
  `object_repr` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `action_flag` smallint(0) UNSIGNED NOT NULL,
  `change_message` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `content_type_id` int(0) NULL DEFAULT NULL,
  `user_id` int(0) NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `django_admin_log_content_type_id_c4bce8eb_fk_django_co`(`content_type_id`) USING BTREE,
  INDEX `django_admin_log_user_id_c564eba6_fk_auth_user_id`(`user_id`) USING BTREE,
  CONSTRAINT `django_admin_log_content_type_id_c4bce8eb_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `django_admin_log_user_id_c564eba6_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of django_admin_log
-- ----------------------------

-- ----------------------------
-- Table structure for django_content_type
-- ----------------------------
DROP TABLE IF EXISTS `django_content_type`;
CREATE TABLE `django_content_type`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `app_label` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `model` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `django_content_type_app_label_model_76bd3d3b_uniq`(`app_label`, `model`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 22 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of django_content_type
-- ----------------------------
INSERT INTO `django_content_type` VALUES (1, 'admin', 'logentry');
INSERT INTO `django_content_type` VALUES (3, 'auth', 'group');
INSERT INTO `django_content_type` VALUES (2, 'auth', 'permission');
INSERT INTO `django_content_type` VALUES (4, 'auth', 'user');
INSERT INTO `django_content_type` VALUES (5, 'contenttypes', 'contenttype');
INSERT INTO `django_content_type` VALUES (21, 'hoimsystem', 'appointment');
INSERT INTO `django_content_type` VALUES (20, 'hoimsystem', 'breach_record');
INSERT INTO `django_content_type` VALUES (22, 'hoimsystem', 'charge');
INSERT INTO `django_content_type` VALUES (7, 'hoimsystem', 'department');
INSERT INTO `django_content_type` VALUES (8, 'hoimsystem', 'doctor');
INSERT INTO `django_content_type` VALUES (19, 'hoimsystem', 'doctor_schedule');
INSERT INTO `django_content_type` VALUES (18, 'hoimsystem', 'medical_record');
INSERT INTO `django_content_type` VALUES (17, 'hoimsystem', 'notice');
INSERT INTO `django_content_type` VALUES (9, 'hoimsystem', 'patient');
INSERT INTO `django_content_type` VALUES (10, 'hoimsystem', 'pharmaceutical');
INSERT INTO `django_content_type` VALUES (16, 'hoimsystem', 'pre_pha');
INSERT INTO `django_content_type` VALUES (15, 'hoimsystem', 'prescription');
INSERT INTO `django_content_type` VALUES (11, 'hoimsystem', 'reg_category');
INSERT INTO `django_content_type` VALUES (14, 'hoimsystem', 'registration');
INSERT INTO `django_content_type` VALUES (12, 'hoimsystem', 'timeslot');
INSERT INTO `django_content_type` VALUES (13, 'hoimsystem', 'users');
INSERT INTO `django_content_type` VALUES (6, 'sessions', 'session');

-- ----------------------------
-- Table structure for django_migrations
-- ----------------------------
DROP TABLE IF EXISTS `django_migrations`;
CREATE TABLE `django_migrations`  (
  `id` bigint(0) NOT NULL AUTO_INCREMENT,
  `app` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `applied` datetime(6) NOT NULL,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 25 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of django_migrations
-- ----------------------------
INSERT INTO `django_migrations` VALUES (1, 'contenttypes', '0001_initial', '2022-12-10 14:53:34.788669');
INSERT INTO `django_migrations` VALUES (2, 'auth', '0001_initial', '2022-12-10 14:53:35.019670');
INSERT INTO `django_migrations` VALUES (3, 'admin', '0001_initial', '2022-12-10 14:53:35.094669');
INSERT INTO `django_migrations` VALUES (4, 'admin', '0002_logentry_remove_auto_add', '2022-12-10 14:53:35.101669');
INSERT INTO `django_migrations` VALUES (5, 'admin', '0003_logentry_add_action_flag_choices', '2022-12-10 14:53:35.108671');
INSERT INTO `django_migrations` VALUES (6, 'contenttypes', '0002_remove_content_type_name', '2022-12-10 14:53:35.151670');
INSERT INTO `django_migrations` VALUES (7, 'auth', '0002_alter_permission_name_max_length', '2022-12-10 14:53:35.183670');
INSERT INTO `django_migrations` VALUES (8, 'auth', '0003_alter_user_email_max_length', '2022-12-10 14:53:35.204673');
INSERT INTO `django_migrations` VALUES (9, 'auth', '0004_alter_user_username_opts', '2022-12-10 14:53:35.212669');
INSERT INTO `django_migrations` VALUES (10, 'auth', '0005_alter_user_last_login_null', '2022-12-10 14:53:35.249679');
INSERT INTO `django_migrations` VALUES (11, 'auth', '0006_require_contenttypes_0002', '2022-12-10 14:53:35.252670');
INSERT INTO `django_migrations` VALUES (12, 'auth', '0007_alter_validators_add_error_messages', '2022-12-10 14:53:35.262671');
INSERT INTO `django_migrations` VALUES (13, 'auth', '0008_alter_user_username_max_length', '2022-12-10 14:53:35.306231');
INSERT INTO `django_migrations` VALUES (14, 'auth', '0009_alter_user_last_name_max_length', '2022-12-10 14:53:35.349230');
INSERT INTO `django_migrations` VALUES (15, 'auth', '0010_alter_group_name_max_length', '2022-12-10 14:53:35.364226');
INSERT INTO `django_migrations` VALUES (16, 'auth', '0011_update_proxy_permissions', '2022-12-10 14:53:35.373229');
INSERT INTO `django_migrations` VALUES (17, 'auth', '0012_alter_user_first_name_max_length', '2022-12-10 14:53:35.405227');
INSERT INTO `django_migrations` VALUES (18, 'hoimsystem', '0001_initial', '2022-12-10 14:53:35.946779');
INSERT INTO `django_migrations` VALUES (19, 'hoimsystem', '0002_medical_record_prescription_id', '2022-12-10 14:53:35.976779');
INSERT INTO `django_migrations` VALUES (20, 'hoimsystem', '0003_charge', '2022-12-10 14:53:36.018779');
INSERT INTO `django_migrations` VALUES (21, 'sessions', '0001_initial', '2022-12-10 14:53:36.039779');
INSERT INTO `django_migrations` VALUES (22, 'hoimsystem', '0004_auto_20221211_1219', '2022-12-11 04:20:10.941427');
INSERT INTO `django_migrations` VALUES (23, 'hoimsystem', '0005_auto_20221211_1325', '2022-12-11 05:26:20.008188');
INSERT INTO `django_migrations` VALUES (24, 'hoimsystem', '0007_alter_appointment_prefer_time', '2022-12-14 04:58:53.254662');
INSERT INTO `django_migrations` VALUES (25, 'hoimsystem', '0008_auto_20221214_1332', '2022-12-14 05:33:55.329497');

-- ----------------------------
-- Table structure for django_session
-- ----------------------------
DROP TABLE IF EXISTS `django_session`;
CREATE TABLE `django_session`  (
  `session_key` varchar(40) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `session_data` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `expire_date` datetime(6) NOT NULL,
  PRIMARY KEY (`session_key`) USING BTREE,
  INDEX `django_session_expire_date_a5c62663`(`expire_date`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of django_session
-- ----------------------------

-- ----------------------------
-- Table structure for hoimsystem_appointment
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_appointment`;
CREATE TABLE `hoimsystem_appointment`  (
  `registration_uuid` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `status` int(0) NOT NULL,
  `department_id_id` int(0) NOT NULL,
  `doctor_id_id` int(0) NOT NULL,
  `patient_id_id` int(0) NOT NULL,
  `prefer_time` varchar(5) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `appointment_time` datetime(6) NOT NULL,
  `time` date NOT NULL,
  `specialist` int(0) NOT NULL,
  PRIMARY KEY (`registration_uuid`) USING BTREE,
  INDEX `hoimsystem_appointme_department_id_id_09fe949e_fk_hoimsyste`(`department_id_id`) USING BTREE,
  INDEX `hoimsystem_appointme_doctor_id_id_019d5983_fk_hoimsyste`(`doctor_id_id`) USING BTREE,
  INDEX `hoimsystem_appointme_patient_id_id_99ed81ff_fk_hoimsyste`(`patient_id_id`) USING BTREE,
  CONSTRAINT `hoimsystem_appointme_department_id_id_09fe949e_fk_hoimsyste` FOREIGN KEY (`department_id_id`) REFERENCES `hoimsystem_department` (`department_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `hoimsystem_appointme_doctor_id_id_019d5983_fk_hoimsyste` FOREIGN KEY (`doctor_id_id`) REFERENCES `hoimsystem_doctor` (`doctor_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `hoimsystem_appointme_patient_id_id_99ed81ff_fk_hoimsyste` FOREIGN KEY (`patient_id_id`) REFERENCES `hoimsystem_patient` (`patient_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_appointment
-- ----------------------------
INSERT INTO `hoimsystem_appointment` VALUES ('0058c5d3b5c843d8b6228573363f12cd', 0, 3, 4, 1, '下午', '2022-12-14 11:29:28.222606', '2022-12-20', 0);
INSERT INTO `hoimsystem_appointment` VALUES ('402c5654d0a34857b71537e215f0dcb7', 2, 1, 1, 1, '上午', '2022-12-14 05:04:22.585636', '2022-12-19', 1);

-- ----------------------------
-- Table structure for hoimsystem_breach_record
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_breach_record`;
CREATE TABLE `hoimsystem_breach_record`  (
  `breach_id` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `registration_id_id` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`breach_id`) USING BTREE,
  INDEX `hoimsystem_breach_re_registration_id_id_111c5fe5_fk_hoimsyste`(`registration_id_id`) USING BTREE,
  CONSTRAINT `hoimsystem_breach_re_registration_id_id_111c5fe5_fk_hoimsyste` FOREIGN KEY (`registration_id_id`) REFERENCES `hoimsystem_registration` (`registration_uuid`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_breach_record
-- ----------------------------

-- ----------------------------
-- Table structure for hoimsystem_charge
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_charge`;
CREATE TABLE `hoimsystem_charge`  (
  `charge_id` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `charge_time` datetime(6) NOT NULL,
  `time` datetime(6) NOT NULL,
  `amount` double NOT NULL,
  `status` int(0) NOT NULL,
  `prescription_id_id` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`charge_id`) USING BTREE,
  INDEX `hoimsystem_charge_prescription_id_id_1f7f8e7c_fk_hoimsyste`(`prescription_id_id`) USING BTREE,
  CONSTRAINT `hoimsystem_charge_prescription_id_id_1f7f8e7c_fk_hoimsyste` FOREIGN KEY (`prescription_id_id`) REFERENCES `hoimsystem_prescription` (`prescription_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_charge
-- ----------------------------
INSERT INTO `hoimsystem_charge` VALUES ('cf8b35b4e8c5421c9e2ef017f14cd0b6', '2022-12-14 10:23:49.180133', '2022-12-14 10:27:48.090139', 37, 1, 'ccbf2c2ba82540b3aced0ebf68e3ee4f');

-- ----------------------------
-- Table structure for hoimsystem_department
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_department`;
CREATE TABLE `hoimsystem_department`  (
  `department_id` int(0) NOT NULL AUTO_INCREMENT,
  `name` varchar(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `phone` varchar(11) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `location` varchar(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `director` int(0) NOT NULL,
  PRIMARY KEY (`department_id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 4 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_department
-- ----------------------------
INSERT INTO `hoimsystem_department` VALUES (1, '口腔科', '123123123', '1423413', 1);
INSERT INTO `hoimsystem_department` VALUES (2, '五官科', '124142314', '32432532453', 1);
INSERT INTO `hoimsystem_department` VALUES (3, 'test', 'test', 'test', 1);
INSERT INTO `hoimsystem_department` VALUES (4, 'lyf的测试科室', '1654564654', '1#1f', 2);

-- ----------------------------
-- Table structure for hoimsystem_doctor
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_doctor`;
CREATE TABLE `hoimsystem_doctor`  (
  `doctor_id` int(0) NOT NULL AUTO_INCREMENT,
  `name` varchar(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `sex` int(0) NOT NULL,
  `title` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `education` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `phone` varchar(11) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `permission` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `department_id_id` int(0) NOT NULL,
  `user_id_id` int(0) NOT NULL,
  PRIMARY KEY (`doctor_id`) USING BTREE,
  INDEX `hoimsystem_doctor_user_id_id_1376ac18_fk_hoimsyste`(`user_id_id`) USING BTREE,
  INDEX `hoimsystem_doctor_department_id_id_d23e01b1_fk_hoimsyste`(`department_id_id`) USING BTREE,
  CONSTRAINT `hoimsystem_doctor_department_id_id_d23e01b1_fk_hoimsyste` FOREIGN KEY (`department_id_id`) REFERENCES `hoimsystem_department` (`department_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `hoimsystem_doctor_user_id_id_1376ac18_fk_hoimsyste` FOREIGN KEY (`user_id_id`) REFERENCES `hoimsystem_users` (`user_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 4 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_doctor
-- ----------------------------
INSERT INTO `hoimsystem_doctor` VALUES (1, 'wms', 1, '主任医生', '硕士', '14234432453', 'director', 1, 2);
INSERT INTO `hoimsystem_doctor` VALUES (2, 'lyf', 1, '实习医生', '硕士', '23432423432', 'director', 2, 3);
INSERT INTO `hoimsystem_doctor` VALUES (3, 'zcj', 0, '副主任医生', '硕士', '15646546521', 'doctor', 4, 5);
INSERT INTO `hoimsystem_doctor` VALUES (4, 'grc', 0, '主治医生', '博士', '15645646546', 'doctor', 3, 6);

-- ----------------------------
-- Table structure for hoimsystem_doctor_schedule
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_doctor_schedule`;
CREATE TABLE `hoimsystem_doctor_schedule`  (
  `schedule_id` int(0) NOT NULL AUTO_INCREMENT,
  `week` varchar(5) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `time` varchar(2) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `number` int(0) NOT NULL,
  `specialist` int(0) NOT NULL,
  `doctor_id_id` int(0) NOT NULL,
  PRIMARY KEY (`schedule_id`) USING BTREE,
  INDEX `hoimsystem_doctor_sc_doctor_id_id_0980a017_fk_hoimsyste`(`doctor_id_id`) USING BTREE,
  CONSTRAINT `hoimsystem_doctor_sc_doctor_id_id_0980a017_fk_hoimsyste` FOREIGN KEY (`doctor_id_id`) REFERENCES `hoimsystem_doctor` (`doctor_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 15 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_doctor_schedule
-- ----------------------------
INSERT INTO `hoimsystem_doctor_schedule` VALUES (1, '星期一', '上午', 122, 1, 1);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (2, '星期二', '上午', 123, 1, 1);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (3, '星期三', '下午', 119, 1, 1);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (4, '星期五', '上午', 123, 1, 1);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (5, '星期一', '上午', 11, 0, 2);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (6, '星期二', '下午', 13, 0, 2);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (7, '星期三', '下午', 13, 0, 2);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (8, '星期四', '下午', 13, 0, 2);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (9, '星期一', '上午', 10, 1, 3);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (10, '星期二', '上午', 10, 1, 3);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (11, '星期三', '上午', 9, 1, 3);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (12, '星期四', '上午', 10, 1, 3);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (13, '星期五', '下午', 10, 1, 3);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (14, '星期一', '下午', 10, 0, 4);
INSERT INTO `hoimsystem_doctor_schedule` VALUES (15, '星期二', '下午', 9, 0, 4);

-- ----------------------------
-- Table structure for hoimsystem_medical_record
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_medical_record`;
CREATE TABLE `hoimsystem_medical_record`  (
  `medical_record_id` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `consultation_time` datetime(6) NOT NULL,
  `symptom` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `result` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `doctor_id_id` int(0) NOT NULL,
  `patient_id_id` int(0) NOT NULL,
  PRIMARY KEY (`medical_record_id`) USING BTREE,
  INDEX `hoimsystem_medical_r_doctor_id_id_c4113468_fk_hoimsyste`(`doctor_id_id`) USING BTREE,
  INDEX `hoimsystem_medical_r_patient_id_id_974c71f3_fk_hoimsyste`(`patient_id_id`) USING BTREE,
  CONSTRAINT `hoimsystem_medical_r_doctor_id_id_c4113468_fk_hoimsyste` FOREIGN KEY (`doctor_id_id`) REFERENCES `hoimsystem_doctor` (`doctor_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `hoimsystem_medical_r_patient_id_id_974c71f3_fk_hoimsyste` FOREIGN KEY (`patient_id_id`) REFERENCES `hoimsystem_patient` (`patient_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_medical_record
-- ----------------------------

-- ----------------------------
-- Table structure for hoimsystem_notice
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_notice`;
CREATE TABLE `hoimsystem_notice`  (
  `notice_id` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `title` varchar(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `content` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `isemergency` int(0) NOT NULL,
  `towho` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `sendtime` datetime(6) NOT NULL,
  `expiredtime` datetime(6) NOT NULL,
  `readnum` int(0) NOT NULL,
  `writer_id` int(0) NOT NULL,
  PRIMARY KEY (`notice_id`) USING BTREE,
  INDEX `hoimsystem_notice_writer_id_d914f713_fk_hoimsystem_users_user_id`(`writer_id`) USING BTREE,
  CONSTRAINT `hoimsystem_notice_writer_id_d914f713_fk_hoimsystem_users_user_id` FOREIGN KEY (`writer_id`) REFERENCES `hoimsystem_users` (`user_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_notice
-- ----------------------------
INSERT INTO `hoimsystem_notice` VALUES ('1f6a35635a60494f90d0c1efa733d8e8', '给医生的通知', '给医生发送的通知，元旦放假安排', 1, '[\'医生\']', '2022-12-14 10:25:13.639154', '2022-12-31 16:00:00.000000', 0, 2);
INSERT INTO `hoimsystem_notice` VALUES ('36524159a53a4b06b61192d779f3acc1', '给病人的停诊通知', '本周一 wms医生停诊', 1, '[\'病人\']', '2022-12-14 10:21:04.805952', '2022-12-15 16:00:00.000000', 0, 1);

-- ----------------------------
-- Table structure for hoimsystem_patient
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_patient`;
CREATE TABLE `hoimsystem_patient`  (
  `patient_id` int(0) NOT NULL AUTO_INCREMENT,
  `name` varchar(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `sex` int(0) NOT NULL,
  `identity` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `birthday` date NOT NULL,
  `phone` varchar(11) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `address` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `permission` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`patient_id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 1 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_patient
-- ----------------------------
INSERT INTO `hoimsystem_patient` VALUES (1, 'lyf', 1, 'lyflyflyf', '2021-12-06', '13588888888', 'sdfsafas', 'allow');

-- ----------------------------
-- Table structure for hoimsystem_pharmaceutical
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_pharmaceutical`;
CREATE TABLE `hoimsystem_pharmaceutical`  (
  `pharmaceutical_id` int(0) NOT NULL AUTO_INCREMENT,
  `name` varchar(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `stock` int(0) NOT NULL,
  `price` double NOT NULL,
  `expireddate` date NOT NULL,
  `purchasing_time` datetime(6) NOT NULL,
  `supplier` varchar(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `remark` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`pharmaceutical_id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 2 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_pharmaceutical
-- ----------------------------
INSERT INTO `hoimsystem_pharmaceutical` VALUES (1, '999感冒灵', 122, 12, '2023-12-06', '2022-12-14 10:08:38.673329', '999药业', '感冒药，避光保存');
INSERT INTO `hoimsystem_pharmaceutical` VALUES (2, '布洛芬', 11, 25, '2024-12-06', '2022-12-14 10:09:26.315832', '生产布洛芬的药厂', '这是布洛芬的测试');

-- ----------------------------
-- Table structure for hoimsystem_pre_pha
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_pre_pha`;
CREATE TABLE `hoimsystem_pre_pha`  (
  `pre_pha_id` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `prescription_id` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `number` int(0) NOT NULL,
  `pharmaceutical_id_id` int(0) NOT NULL,
  PRIMARY KEY (`pre_pha_id`) USING BTREE,
  INDEX `hoimsystem_pre_pha_pharmaceutical_id_id_6b108316_fk_hoimsyste`(`pharmaceutical_id_id`) USING BTREE,
  CONSTRAINT `hoimsystem_pre_pha_pharmaceutical_id_id_6b108316_fk_hoimsyste` FOREIGN KEY (`pharmaceutical_id_id`) REFERENCES `hoimsystem_pharmaceutical` (`pharmaceutical_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_pre_pha
-- ----------------------------
INSERT INTO `hoimsystem_pre_pha` VALUES ('850ac4573938481490b7a21abf01ca68', 'ccbf2c2b-a825-40b3-aced-0ebf68e3ee4f', 1, 2);
INSERT INTO `hoimsystem_pre_pha` VALUES ('a66054d85367437583cb288901112757', 'ccbf2c2b-a825-40b3-aced-0ebf68e3ee4f', 1, 1);

-- ----------------------------
-- Table structure for hoimsystem_prescription
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_prescription`;
CREATE TABLE `hoimsystem_prescription`  (
  `prescription_id` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `doctor_id_id` int(0) NOT NULL,
  `patient_id_id` int(0) NOT NULL,
  PRIMARY KEY (`prescription_id`) USING BTREE,
  INDEX `hoimsystem_prescript_doctor_id_id_484c7d19_fk_hoimsyste`(`doctor_id_id`) USING BTREE,
  INDEX `hoimsystem_prescript_patient_id_id_8196b4d0_fk_hoimsyste`(`patient_id_id`) USING BTREE,
  CONSTRAINT `hoimsystem_prescript_doctor_id_id_484c7d19_fk_hoimsyste` FOREIGN KEY (`doctor_id_id`) REFERENCES `hoimsystem_doctor` (`doctor_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `hoimsystem_prescript_patient_id_id_8196b4d0_fk_hoimsyste` FOREIGN KEY (`patient_id_id`) REFERENCES `hoimsystem_patient` (`patient_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_prescription
-- ----------------------------
INSERT INTO `hoimsystem_prescription` VALUES ('ccbf2c2ba82540b3aced0ebf68e3ee4f', 1, 1);

-- ----------------------------
-- Table structure for hoimsystem_reg_category
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_reg_category`;
CREATE TABLE `hoimsystem_reg_category`  (
  `reg_category_id` int(0) NOT NULL AUTO_INCREMENT,
  `name` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`reg_category_id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_reg_category
-- ----------------------------

-- ----------------------------
-- Table structure for hoimsystem_registration
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_registration`;
CREATE TABLE `hoimsystem_registration`  (
  `registration_uuid` char(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `registration_id` int(0) NOT NULL,
  `status` int(0) NOT NULL,
  `department_id_id` int(0) NOT NULL,
  `doctor_id_id` int(0) NOT NULL,
  `patient_id_id` int(0) NOT NULL,
  `time` datetime(6) NOT NULL,
  `specialist` int(0) NOT NULL,
  PRIMARY KEY (`registration_uuid`) USING BTREE,
  INDEX `hoimsystem_registrat_department_id_id_9e29001f_fk_hoimsyste`(`department_id_id`) USING BTREE,
  INDEX `hoimsystem_registrat_doctor_id_id_ffad0b96_fk_hoimsyste`(`doctor_id_id`) USING BTREE,
  INDEX `hoimsystem_registrat_patient_id_id_47940776_fk_hoimsyste`(`patient_id_id`) USING BTREE,
  CONSTRAINT `hoimsystem_registrat_department_id_id_9e29001f_fk_hoimsyste` FOREIGN KEY (`department_id_id`) REFERENCES `hoimsystem_department` (`department_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `hoimsystem_registrat_doctor_id_id_ffad0b96_fk_hoimsyste` FOREIGN KEY (`doctor_id_id`) REFERENCES `hoimsystem_doctor` (`doctor_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `hoimsystem_registrat_patient_id_id_47940776_fk_hoimsyste` FOREIGN KEY (`patient_id_id`) REFERENCES `hoimsystem_patient` (`patient_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_registration
-- ----------------------------
INSERT INTO `hoimsystem_registration` VALUES ('0c68fe4b608a4a3cad57e48eebb69565', 1, 3, 2, 2, 1, '2022-12-12 12:10:19.437884', 0);
INSERT INTO `hoimsystem_registration` VALUES ('7c73f14b9bc34e7ea31d0cc36cc10015', 1, 3, 1, 1, 1, '2022-12-14 05:24:15.389492', 1);
INSERT INTO `hoimsystem_registration` VALUES ('d40736e74c9a4aff996f9170bec818ab', 1, 0, 4, 3, 1, '2022-12-14 11:26:46.031282', 1);

-- ----------------------------
-- Table structure for hoimsystem_timeslot
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_timeslot`;
CREATE TABLE `hoimsystem_timeslot`  (
  `timeslot_id` int(0) NOT NULL AUTO_INCREMENT,
  `time` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`timeslot_id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_timeslot
-- ----------------------------

-- ----------------------------
-- Table structure for hoimsystem_users
-- ----------------------------
DROP TABLE IF EXISTS `hoimsystem_users`;
CREATE TABLE `hoimsystem_users`  (
  `user_id` int(0) NOT NULL AUTO_INCREMENT,
  `username` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `password` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `user_role` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`user_id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 6 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of hoimsystem_users
-- ----------------------------
INSERT INTO `hoimsystem_users` VALUES (1, 'palpitate', 'palpitate', 'admin');
INSERT INTO `hoimsystem_users` VALUES (2, 'wms', 'password', 'director');
INSERT INTO `hoimsystem_users` VALUES (3, 'lyf', 'password', 'director');
INSERT INTO `hoimsystem_users` VALUES (4, 'lyflyflyf', 'password', 'patient');
INSERT INTO `hoimsystem_users` VALUES (5, 'zcj', 'password', 'doctor');
INSERT INTO `hoimsystem_users` VALUES (6, 'grc', 'password', 'doctor');

SET FOREIGN_KEY_CHECKS = 1;
