import React, { Component } from 'react';
import { Avatar, Tooltip } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';

import './index.css';
import { Row, Col } from 'antd';
import Colorbar from '../../assets/bosch-colorbar.jpg';
import Logo from '../../assets/bosch-app-pms.jpg';

// ⭐ 引入 Context
import { AppContext } from '../../context/AppContext';

export default class Header extends Component {
  
  // ⭐ class 组件使用 context 的方式
  static contextType = AppContext;

  render() {
    const { user, downloadClient } = this.context;

    return (
      <div>
        <Row>
          <img src={Colorbar} alt="ColorBar" className="colorbar" />
        </Row>

        <Row className='header' type="flex" justify="start">
          <Col span={8}>
            <img src={Logo} alt="Logo" className="logo" />
          </Col>

          <Col span={8} offset={8}>
            <Row span={24} type="flex" justify="end">

              {/* ⭐ 下载按钮：不再写 URL → 调用 Context 中的 downloadClient() */}
              <Tooltip title="下载客户端 Client.exe">
                <Avatar
                  shape="square"
                  size={40}
                  style={{
                    backgroundColor: '#238691ff',
                    cursor: 'pointer',
                    marginRight: 6,
                  }}
                  onClick={downloadClient}   // ⭐ 替换硬编码 URL
                >
                  <DownloadOutlined style={{ fontSize: 20, color: '#fff' }} />
                </Avatar>
              </Tooltip>

              {/* ⭐ 用户 Avatar：依然显示用户名 */}
              <Avatar
                shape="square"
                size={40}
                style={{ backgroundColor: '#198e3eff' }}
              >
                {user?.username?.slice(0, 2).toUpperCase()}
              </Avatar>

            </Row>
          </Col>
        </Row>
      </div>
    );
  }
}
