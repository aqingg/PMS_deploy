import React, { Component } from 'react'
import { Avatar, Tooltip } from 'antd';
import './index.css'
import { Row, Col } from 'antd';
import Colorbar from '../../assets/bosch-colorbar.jpg';
import Logo from '../../assets/bosch-app-pms.jpg';
export default class Header extends Component {
  handleLogoClick = () => {
    // 跳转到前端 A（APP-PUMA）
    window.location.href = "https://cccn.apac.bosch.com/APP-PMS-GATE/";
  };
  render() {
    const { user } = this.props;
    return (
      <div>
        <Row>
          <img src={Colorbar} alt="ColorBar" className="colorbar"/>
        </Row>
        <Row className='header' type="flex" justify="start">
          <Col span={8}>
          <Tooltip title="Jump to PUMA HomePage">
            <img
            src={Logo}
              alt="Logo"
              className="logo"
              onClick={this.handleLogoClick}
              style={{ cursor: "pointer" }}
            />
          </Tooltip>
          </Col>
          <Col span={8} offset={8}>
            <Row span={24} type="flex" justify="end">
                <Avatar shape="square" style={{ backgroundColor: '#5da7e4ff' }}>{user.username.slice(0, 2).toUpperCase()}</Avatar>
            </Row>
          </Col>
        </Row>
      </div>
    );
  }
}

