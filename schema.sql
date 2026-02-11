-- 发票报销管理系统 数据库建表脚本
-- 适用于 PostgreSQL 和 MySQL
-- 生成日期: 2026-02-11

-- ============================================
-- 用户表 (扩展 Django 的 AbstractUser)
-- ============================================
CREATE TABLE IF NOT EXISTS core_user (
    id SERIAL PRIMARY KEY,
    password VARCHAR(128) NOT NULL,
    last_login TIMESTAMP NULL,
    is_superuser BOOLEAN NOT NULL DEFAULT FALSE,
    username VARCHAR(150) NOT NULL UNIQUE,
    first_name VARCHAR(150) NOT NULL DEFAULT '',
    last_name VARCHAR(150) NOT NULL DEFAULT '',
    email VARCHAR(254) NOT NULL DEFAULT '',
    is_staff BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    date_joined TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    role VARCHAR(20) NOT NULL DEFAULT 'EMPLOYEE',
    
    CONSTRAINT core_user_role_check CHECK (role IN ('EMPLOYEE', 'ACCOUNTANT'))
);

-- 用户表索引
CREATE INDEX idx_core_user_username ON core_user(username);
CREATE INDEX idx_core_user_role ON core_user(role);
CREATE INDEX idx_core_user_is_active ON core_user(is_active);

-- ============================================
-- 发票表
-- ============================================
CREATE TABLE IF NOT EXISTS core_invoice (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    file VARCHAR(100) NOT NULL,
    amount DECIMAL(10, 2) NULL,
    invoice_date DATE NULL,
    product_name VARCHAR(255) NULL,
    specification_model VARCHAR(255) NULL,
    unit VARCHAR(50) NULL,
    quantity VARCHAR(50) NULL,
    unit_price VARCHAR(50) NULL,
    money_without_tax VARCHAR(50) NULL,
    tax_rate VARCHAR(50) NULL,
    tax_amount VARCHAR(50) NULL,
    amount_in_words VARCHAR(255) NULL,
    amount_in_figures VARCHAR(50) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_invoice_user FOREIGN KEY (user_id) REFERENCES core_user(id) ON DELETE CASCADE
);

-- 发票表索引
CREATE INDEX idx_invoice_user_id ON core_invoice(user_id);
CREATE INDEX idx_invoice_created_at ON core_invoice(created_at DESC);
CREATE INDEX idx_invoice_invoice_date ON core_invoice(invoice_date);
CREATE INDEX idx_invoice_amount ON core_invoice(amount);
-- 组合索引：用于查询用户的发票列表并按创建时间排序
CREATE INDEX idx_invoice_user_created ON core_invoice(user_id, created_at DESC);

-- ============================================
-- 报销单表
-- ============================================
CREATE TABLE IF NOT EXISTS core_reimbursement (
    id SERIAL PRIMARY KEY,
    applicant_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    reviewer_id INTEGER NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_reimbursement_applicant FOREIGN KEY (applicant_id) REFERENCES core_user(id) ON DELETE CASCADE,
    CONSTRAINT fk_reimbursement_reviewer FOREIGN KEY (reviewer_id) REFERENCES core_user(id) ON DELETE SET NULL,
    CONSTRAINT core_reimbursement_status_check CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED'))
);

-- 报销单表索引
CREATE INDEX idx_reimbursement_applicant_id ON core_reimbursement(applicant_id);
CREATE INDEX idx_reimbursement_reviewer_id ON core_reimbursement(reviewer_id);
CREATE INDEX idx_reimbursement_status ON core_reimbursement(status);
CREATE INDEX idx_reimbursement_created_at ON core_reimbursement(created_at DESC);
-- 组合索引：用于财务人员查询待审批报销单
CREATE INDEX idx_reimbursement_status_created ON core_reimbursement(status, created_at DESC);
-- 组合索引：用于查询用户的报销单
CREATE INDEX idx_reimbursement_applicant_status ON core_reimbursement(applicant_id, status);

-- ============================================
-- 报销单-发票 多对多关系表
-- ============================================
CREATE TABLE IF NOT EXISTS core_reimbursement_invoices (
    id SERIAL PRIMARY KEY,
    reimbursement_id INTEGER NOT NULL,
    invoice_id INTEGER NOT NULL,
    
    CONSTRAINT fk_reimbursement_invoices_reimbursement FOREIGN KEY (reimbursement_id) REFERENCES core_reimbursement(id) ON DELETE CASCADE,
    CONSTRAINT fk_reimbursement_invoices_invoice FOREIGN KEY (invoice_id) REFERENCES core_invoice(id) ON DELETE CASCADE,
    CONSTRAINT unique_reimbursement_invoice UNIQUE (reimbursement_id, invoice_id)
);

-- 多对多关系表索引
CREATE INDEX idx_reimbursement_invoices_reimbursement ON core_reimbursement_invoices(reimbursement_id);
CREATE INDEX idx_reimbursement_invoices_invoice ON core_reimbursement_invoices(invoice_id);

-- ============================================
-- 注释说明
-- ============================================
COMMENT ON TABLE core_user IS '用户表，包含员工和财务审批人';
COMMENT ON COLUMN core_user.role IS '用户角色：EMPLOYEE-员工, ACCOUNTANT-财务';

COMMENT ON TABLE core_invoice IS '发票表，存储上传的发票及OCR解析结果';
COMMENT ON COLUMN core_invoice.file IS '发票文件路径';
COMMENT ON COLUMN core_invoice.amount IS 'OCR解析的发票金额';
COMMENT ON COLUMN core_invoice.invoice_date IS 'OCR解析的发票日期';

COMMENT ON TABLE core_reimbursement IS '报销单表';
COMMENT ON COLUMN core_reimbursement.status IS '报销单状态：PENDING-待审批, APPROVED-已批准, REJECTED-已驳回';
COMMENT ON COLUMN core_reimbursement.applicant_id IS '申请人ID';
COMMENT ON COLUMN core_reimbursement.reviewer_id IS '审批人ID（财务）';

COMMENT ON TABLE core_reimbursement_invoices IS '报销单与发票的多对多关系表';

-- ============================================
-- 示例数据（可选）
-- ============================================
-- 创建超级管理员用户
-- INSERT INTO core_user (username, password, email, is_superuser, is_staff, role) 
-- VALUES ('admin', 'pbkdf2_sha256$...', 'admin@example.com', TRUE, TRUE, 'ACCOUNTANT');

-- 创建普通员工
-- INSERT INTO core_user (username, password, email, role) 
-- VALUES ('employee1', 'pbkdf2_sha256$...', 'employee1@example.com', 'EMPLOYEE');

-- 创建财务审批人
-- INSERT INTO core_user (username, password, email, role) 
-- VALUES ('accountant1', 'pbkdf2_sha256$...', 'accountant1@example.com', 'ACCOUNTANT');
